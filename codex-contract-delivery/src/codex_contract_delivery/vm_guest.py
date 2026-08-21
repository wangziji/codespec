"""Guest-side entry point for isolated Codex worker tasks."""

from __future__ import annotations

import argparse
import base64
import binascii
import errno
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import WorkerKind


_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TERM_GRACE_SECONDS = 1.0
_KILL_GRACE_SECONDS = 1.0
_PINNED_CODEX_VERSION = "0.147.0"
_GUEST_CODEX_HOME = Path("/home/mark.guest/.codex")
MAX_SOURCE_SNAPSHOT_BYTES = 24 * 1024 * 1024
MAX_WORKER_REQUEST_BYTES = ((MAX_SOURCE_SNAPSHOT_BYTES + 2) // 3) * 4 + 1024 * 1024
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "approved_context",
        "allowed_paths",
        "effect_id",
        "fence",
        "task_fingerprint",
        "source_snapshot_sha256",
        "source_snapshot_b64",
    }
)


@dataclass(frozen=True)
class GuestRequest:
    approved_context: str
    allowed_paths: tuple[str, ...]
    effect_id: str
    fence: int
    task_fingerprint: str
    source_snapshot_sha256: str
    source_snapshot: bytes


def check_sandbox_prerequisites(
    *,
    bwrap: Path = Path("/usr/bin/bwrap"),
    apparmor_userns_sysctl: Path = Path(
        "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
    ),
    apparmor_enabled: Path = Path("/sys/module/apparmor/parameters/enabled"),
) -> None:
    if not bwrap.is_absolute() or not bwrap.is_file() or not os.access(bwrap, os.X_OK):
        raise RuntimeError("bubblewrap sandbox prerequisite is unavailable")
    try:
        restriction = apparmor_userns_sysctl.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(
            "cannot verify apparmor_restrict_unprivileged_userns"
        ) from error
    if restriction != "1":
        raise RuntimeError("apparmor_restrict_unprivileged_userns must remain 1")
    try:
        enabled = apparmor_enabled.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("cannot verify AppArmor is enabled") from error
    if enabled != "Y":
        raise RuntimeError("AppArmor must be enabled for the worker sandbox")
    completed = subprocess.run(
        (
            str(bwrap),
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "/usr/bin/true",
        ),
        shell=False,
        capture_output=True,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise RuntimeError("bubblewrap AppArmor functional probe failed")


def _runtime_file_identity(path: Path) -> dict[str, object]:
    resolved = path.resolve(strict=True)
    descriptor = os.open(
        resolved,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise RuntimeError("guest runtime identity is not regular")
        digest = sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return {
            "path": str(resolved),
            "device": details.st_dev,
            "inode": details.st_ino,
            "mode": details.st_mode,
            "size": details.st_size,
            "mtime_ns": details.st_mtime_ns,
            "sha256": digest.hexdigest(),
        }
    finally:
        os.close(descriptor)


def runtime_attestation(
    *,
    codex_executable: Path = Path("/usr/local/bin/codex"),
    runner: Path | None = None,
) -> dict[str, object]:
    """Prove the fixed guest runner/runtime and its read-only source mount."""
    runner_path = Path(__file__) if runner is None else runner
    runner_real = runner_path.resolve(strict=True)
    mount_options: set[str] | None = None
    selected_mount: Path | None = None
    longest = -1
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError("guest mount authority is unavailable") from error
    for line in lines:
        fields = line.split(" ")
        if len(fields) < 10 or "-" not in fields:
            continue
        mount_point = Path(fields[4].replace("\\040", " "))
        try:
            runner_real.relative_to(mount_point)
        except ValueError:
            continue
        if len(str(mount_point)) > longest:
            longest = len(str(mount_point))
            mount_options = set(fields[5].split(","))
            selected_mount = mount_point
    if mount_options is None or selected_mount is None:
        raise RuntimeError("guest runner mount authority is unavailable")
    if "ro" not in mount_options:
        probe = selected_mount / f".cdd-ro-attest-{os.getuid()}-{os.getpid()}"
        try:
            descriptor = os.open(
                probe,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
                raise RuntimeError(
                    "guest runner mount probe failed ambiguously"
                ) from error
        else:
            os.close(descriptor)
            probe.unlink(missing_ok=True)
            raise RuntimeError("guest runner mount is writable")
    check_sandbox_prerequisites()
    environment = {
        name: os.environ[name]
        for name in ("HOME", "PATH", "LANG", "LC_ALL", "CODEX_HOME")
        if name in os.environ
    }
    validate_codex_version(codex_executable, environment)
    return {
        "type": "cdd.vm.attestation",
        "schema_version": "1.0",
        "runner": _runtime_file_identity(runner_real),
        "python": _runtime_file_identity(Path(sys.executable)),
        "codex": _runtime_file_identity(codex_executable),
        "codex_version": _PINNED_CODEX_VERSION,
        "runner_mount_readonly": True,
        "sandbox_prerequisites": True,
    }


def execute_guest(
    *,
    workspace_base: Path,
    kind: str,
    expected_fingerprint: str,
    expected_snapshot_digest: str,
    codex_executable: Path,
    request_text: str,
    guest_codex_home: Path = _GUEST_CODEX_HOME,
) -> subprocess.CompletedProcess[str]:
    request = parse_request(
        request_text,
        expected_fingerprint=expected_fingerprint,
    )
    if kind not in {"analysis", "implementation"}:
        raise ValueError("unknown worker kind")
    base = workspace_base.resolve(strict=True)
    if Path(os.path.abspath(workspace_base)) != base:
        raise ValueError("workspace base cannot be a symlink")
    if not base.is_dir():
        raise ValueError("workspace base must be a directory")
    if (
        _DIGEST.fullmatch(expected_snapshot_digest) is None
        or request.source_snapshot_sha256 != expected_snapshot_digest
    ):
        raise ValueError("source snapshot digest drifted")
    environment = {
        name: os.environ[name]
        for name in ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "CODEX_HOME")
        if name in os.environ
    }
    codex_home = _codex_home(environment, expected=guest_codex_home)
    environment["CODEX_HOME"] = str(codex_home)
    validate_codex_version(codex_executable, environment)
    control_dir, state_path, cancelled_path = _control_paths(
        base, request.effect_id, request.fence
    )
    _ensure_control_dir(control_dir)
    if cancelled_path.exists():
        raise RuntimeError("guest task was already cancelled")
    workspace = Path(
        tempfile.mkdtemp(
            prefix=(
                f"{request.effect_id}-{request.fence}-{request.task_fingerprint[:16]}-"
            ),
            dir=base,
        )
    ).resolve(strict=True)
    process: subprocess.Popen[str] | None = None
    try:
        _write_control_state(
            state_path,
            request.task_fingerprint,
            workspace,
            process_group=None,
        )
        _extract_source_snapshot(request.source_snapshot, workspace)
        _git(workspace, "init", "-q")
        _git(workspace, "config", "user.email", "worker@cdd.invalid")
        _git(workspace, "config", "user.name", "CDD Isolated Worker")
        _git(workspace, "add", "-f", "-A")
        _git(workspace, "commit", "-qm", "controller baseline")
        command = build_codex_command(
            codex_executable,
            kind,
            workspace,
            codex_home=codex_home,
        )
        environment["CDD_IDEMPOTENCY_KEY"] = request.effect_id
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        _write_control_state(
            state_path,
            request.task_fingerprint,
            workspace,
            process_group=process.pid,
        )
        if cancelled_path.exists():
            _terminate_process_group(process.pid)
        stdout_text, stderr_text = process.communicate(input=request.approved_context)
        _git(workspace, "add", "-f", "-N", "-A")
        patch = _git_bytes(workspace, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
        name_status = _git_bytes(workspace, "diff", "--name-status", "-z", "HEAD", "--")
        record = {
            "type": "cdd.vm.result",
            "schema_version": "1.0",
            "task_fingerprint": request.task_fingerprint,
            "patch_sha256": sha256(patch).hexdigest(),
            "patch_b64": base64.b64encode(patch).decode("ascii"),
            "name_status_b64": base64.b64encode(name_status).decode("ascii"),
        }
        stdout = (
            (stdout_text or "")
            + json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr_text or "",
        )
    finally:
        if process is not None and process.poll() is None:
            try:
                _terminate_process_group(process.pid)
                process.wait(timeout=_KILL_GRACE_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            shutil.rmtree(workspace)
        except OSError:
            pass
        try:
            state_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            control_dir.rmdir()
        except OSError:
            pass


def _control_paths(base: Path, effect_id: str, fence: int) -> tuple[Path, Path, Path]:
    if _IDENTIFIER.fullmatch(effect_id) is None:
        raise ValueError("effect id is invalid")
    if not isinstance(fence, int) or isinstance(fence, bool) or fence <= 0:
        raise ValueError("effect fence is invalid")
    control = base / ".cdd-control"
    return (
        control,
        control / f"{effect_id}.{fence}.json",
        control / f"{effect_id}.{fence}.cancelled",
    )


def _ensure_control_dir(control: Path) -> None:
    control.mkdir(mode=0o700, exist_ok=True)
    if control.is_symlink() or not control.is_dir():
        raise RuntimeError("guest control directory is unsafe")
    control.chmod(0o700)


def _write_control_state(
    path: Path,
    task_fingerprint: str,
    workspace: Path,
    *,
    process_group: int | None,
) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(
        {
            "schema_version": "1.0",
            "task_fingerprint": task_fingerprint,
            "workspace": str(workspace),
            "process_group": process_group,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _terminate_process_group(process_group: int) -> None:
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return


def cancel_guest_task(
    workspace_base: Path,
    effect_id: str,
    task_fingerprint: str,
    fence: int,
) -> None:
    if _DIGEST.fullmatch(task_fingerprint) is None:
        raise ValueError("task fingerprint is invalid")
    base = workspace_base.resolve(strict=True)
    if Path(os.path.abspath(workspace_base)) != base:
        raise ValueError("workspace base cannot be a symlink")
    control_dir, state_path, cancelled_path = _control_paths(base, effect_id, fence)
    _ensure_control_dir(control_dir)
    marker = json.dumps(
        {
            "schema_version": "1.0",
            "task_fingerprint": task_fingerprint,
            "fence": fence,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        descriptor = os.open(
            cancelled_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        if cancelled_path.read_text(encoding="utf-8") != marker:
            raise RuntimeError("guest cancellation identity conflicts")
    else:
        try:
            os.write(descriptor, marker.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    deadline = time.monotonic() + _TERM_GRACE_SECONDS
    record: dict[str, object] | None = None
    while time.monotonic() < deadline and state_path.exists():
        try:
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.02)
            continue
        if not isinstance(candidate, dict):
            raise TypeError("guest cancellation state is malformed")
        record = candidate
        if candidate.get("process_group") is not None:
            break
        time.sleep(0.02)
    if record is None:
        return
    if (
        set(record)
        != {
            "schema_version",
            "task_fingerprint",
            "workspace",
            "process_group",
        }
        or record.get("schema_version") != "1.0"
    ):
        raise RuntimeError("guest cancellation state is malformed")
    if record.get("task_fingerprint") != task_fingerprint:
        raise RuntimeError("guest cancellation task fingerprint conflicts")
    workspace_value = record.get("workspace")
    if not isinstance(workspace_value, str):
        raise TypeError("guest cancellation workspace is malformed")
    workspace = Path(workspace_value)
    if not workspace.is_relative_to(base) or not workspace.name.startswith(
        f"{effect_id}-{fence}-{task_fingerprint[:16]}-"
    ):
        raise RuntimeError("guest cancellation workspace escapes its task")
    process_group = record.get("process_group")
    if process_group is not None:
        if not isinstance(process_group, int) or process_group <= 1:
            raise RuntimeError("guest cancellation process group is malformed")
        _terminate_process_group(process_group)
    cleanup_deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < cleanup_deadline and state_path.exists():
        time.sleep(0.02)
    if state_path.exists():
        shutil.rmtree(workspace, ignore_errors=False)
        state_path.unlink(missing_ok=True)


def _extract_source_snapshot(snapshot: bytes, workspace: Path) -> None:
    """Materialize only the regular, controller-attested archive subset."""
    seen: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:") as archive:
            _extract_snapshot_members(archive, workspace, seen)
    except tarfile.TarError as error:
        raise RuntimeError("source snapshot archive is malformed") from error


def _extract_snapshot_members(
    archive: tarfile.TarFile, workspace: Path, seen: set[str]
) -> None:
    for member in archive:
        candidate = Path(member.name)
        if (
            not member.isfile()
            or member.name in seen
            or not member.name
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.parts[0] == ".codex"
            or candidate.name == ".mcp.json"
            or member.mode not in {0o644, 0o755}
            or member.pax_headers
        ):
            raise RuntimeError("source snapshot contains an unsupported entry")
        seen.add(member.name)
        destination = workspace / candidate
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if destination.parent.resolve(strict=True).is_relative_to(workspace) is False:
            raise RuntimeError("source snapshot path escapes the workspace")
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError("source snapshot entry is unavailable")
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            member.mode,
        )
        try:
            remaining = member.size
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise RuntimeError("source snapshot entry is truncated")
                os.write(descriptor, chunk)
                remaining -= len(chunk)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            source.close()


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        shell=False,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("isolated guest git operation failed")


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        shell=False,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("isolated guest git export failed")
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if "--attest" in values:
        parser = argparse.ArgumentParser(prog="cdd-vm-guest-attest")
        parser.add_argument("--attest", action="store_true", required=True)
        parser.add_argument("--json", action="store_true", required=True)
        parser.parse_args(values)
        try:
            record = runtime_attestation()
        except (OSError, RuntimeError, ValueError) as error:
            sys.stderr.write(f"CDD guest attestation failed closed: {error}\n")
            return 70
        sys.stdout.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        sys.stdout.write("\n")
        return 0
    if "--cancel-effect" in values:
        parser = argparse.ArgumentParser(prog="cdd-vm-guest-cancel")
        parser.add_argument("--workspace-base", type=Path, required=True)
        parser.add_argument("--authority-digest", required=True)
        parser.add_argument("--cancel-effect", required=True)
        parser.add_argument("--cancel-task-fingerprint", required=True)
        parser.add_argument("--cancel-fence", type=int, required=True)
        parser.add_argument("--json", action="store_true", required=True)
        arguments = parser.parse_args(values)
        try:
            if _DIGEST.fullmatch(arguments.authority_digest) is None:
                raise ValueError("worker authority digest is invalid")
            cancel_guest_task(
                arguments.workspace_base,
                arguments.cancel_effect,
                arguments.cancel_task_fingerprint,
                arguments.cancel_fence,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            sys.stderr.write(f"CDD guest cancellation failed closed: {error}\n")
            return 70
        sys.stdout.write('{"type":"cdd.vm.cancelled"}\n')
        return 0
    parser = argparse.ArgumentParser(prog="cdd-vm-guest")
    parser.add_argument("--workspace-base", type=Path, required=True)
    parser.add_argument("--authority-digest", required=True)
    parser.add_argument("--source-snapshot-digest", required=True)
    parser.add_argument("--kind", choices=("analysis", "implementation"), required=True)
    parser.add_argument("--task-fingerprint", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    arguments = parser.parse_args(values)
    if _DIGEST.fullmatch(arguments.authority_digest) is None:
        parser.error("worker authority digest is invalid")
    request_text = sys.stdin.read(MAX_WORKER_REQUEST_BYTES + 1)
    if len(request_text) > MAX_WORKER_REQUEST_BYTES:
        parser.error("worker request exceeds the bounded snapshot envelope")
    try:
        check_sandbox_prerequisites()
        completed = execute_guest(
            workspace_base=arguments.workspace_base,
            kind=arguments.kind,
            expected_fingerprint=arguments.task_fingerprint,
            expected_snapshot_digest=arguments.source_snapshot_digest,
            codex_executable=Path("/usr/local/bin/codex"),
            request_text=request_text,
        )
    except (OSError, RuntimeError, ValueError) as error:
        sys.stderr.write(f"CDD guest failed closed: {error}\n")
        return 70
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def build_codex_command(
    codex_executable: Path,
    kind: WorkerKind | str,
    workspace: Path,
    *,
    codex_home: Path = _GUEST_CODEX_HOME,
) -> tuple[str, ...]:
    value = kind.value if hasattr(kind, "value") else str(kind)
    if value not in {"analysis", "implementation"}:
        raise ValueError("unknown worker kind")
    if (
        not codex_executable.is_absolute()
        or not workspace.is_absolute()
        or not codex_home.is_absolute()
    ):
        raise ValueError("Codex executable, workspace, and home must be absolute")
    access = "read" if value == "analysis" else "write"
    profile_override = (
        f"permissions.cdd-{value}={{ filesystem = {{ "
        '":root" = "deny", ":minimal" = "read", '
        f'":workspace_roots" = {{ "." = "{access}" }}, '
        f'{json.dumps(str(codex_home))} = "deny" }}, '
        "network = { enabled = false } }"
    )
    return (
        str(codex_executable),
        "exec",
        "--ignore-user-config",
        "-c",
        f'default_permissions="cdd-{value}"',
        "-c",
        profile_override,
        "--strict-config",
        "--ephemeral",
        "--ignore-rules",
        "--cd",
        str(workspace),
        "--json",
        "-",
    )


def _codex_home(environment: dict[str, str], *, expected: Path) -> Path:
    raw = environment.get("CODEX_HOME")
    if raw is None:
        home = environment.get("HOME")
        if home is None:
            raise RuntimeError("permission profile home is unavailable")
        raw = str(Path(home) / ".codex")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise RuntimeError("permission profile home must be absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("permission profile home is unavailable") from error
    if (
        resolved != Path(os.path.abspath(candidate))
        or resolved != expected.resolve(strict=True)
        or not resolved.is_dir()
    ):
        raise RuntimeError("permission profile home is a symlink or not a directory")
    return resolved


def validate_codex_version(
    codex_executable: Path,
    environment: dict[str, str],
) -> None:
    if not codex_executable.is_absolute():
        raise RuntimeError("Codex CLI executable must be absolute")
    try:
        details = codex_executable.stat()
    except OSError as error:
        raise RuntimeError("Codex CLI executable is unavailable") from error
    if not stat.S_ISREG(details.st_mode) or not os.access(codex_executable, os.X_OK):
        raise RuntimeError("Codex CLI executable identity is unsafe")
    completed = subprocess.run(
        (str(codex_executable), "--version"),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env=environment,
    )
    expected = f"codex-cli {_PINNED_CODEX_VERSION}"
    if completed.returncode != 0 or completed.stdout.strip() != expected:
        raise RuntimeError(
            f"Codex CLI version must be pinned to {_PINNED_CODEX_VERSION}"
        )


def parse_request(value: str, *, expected_fingerprint: str) -> GuestRequest:
    try:
        record = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("worker request must be valid JSON") from error
    if not isinstance(record, dict) or set(record) != _REQUEST_FIELDS:
        raise ValueError("worker request is structurally unknown")
    if record["schema_version"] != "1.0":
        raise ValueError("worker request schema version is unknown")
    context = record["approved_context"]
    if not isinstance(context, str) or not context.strip() or "\x00" in context:
        raise ValueError("approved context is invalid")
    effect_id = record["effect_id"]
    if not isinstance(effect_id, str) or _IDENTIFIER.fullmatch(effect_id) is None:
        raise ValueError("effect id is invalid")
    fence = record["fence"]
    if not isinstance(fence, int) or isinstance(fence, bool) or fence <= 0:
        raise ValueError("effect fence is invalid")
    fingerprint = record["task_fingerprint"]
    if (
        not isinstance(fingerprint, str)
        or _DIGEST.fullmatch(fingerprint) is None
        or fingerprint != expected_fingerprint
    ):
        raise ValueError("task fingerprint drifted")
    snapshot_digest = record["source_snapshot_sha256"]
    encoded_snapshot = record["source_snapshot_b64"]
    if (
        not isinstance(snapshot_digest, str)
        or _DIGEST.fullmatch(snapshot_digest) is None
    ):
        raise ValueError("source snapshot digest is invalid")
    if not isinstance(encoded_snapshot, str):
        raise TypeError("source snapshot payload is invalid")
    try:
        snapshot = base64.b64decode(encoded_snapshot, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("source snapshot payload is invalid") from error
    if (
        len(snapshot) > MAX_SOURCE_SNAPSHOT_BYTES
        or sha256(snapshot).hexdigest() != snapshot_digest
    ):
        raise ValueError("source snapshot payload drifted")
    raw_paths = record["allowed_paths"]
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("allowed paths must be a non-empty list")
    paths: list[str] = []
    for item in raw_paths:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ValueError("allowed path is invalid")
        candidate = Path(item)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("allowed path escapes the workspace")
        normalized = candidate.as_posix().rstrip("/") or "."
        if normalized in paths:
            raise ValueError("allowed paths contain a duplicate")
        paths.append(normalized)
    return GuestRequest(
        context,
        tuple(paths),
        effect_id,
        fence,
        fingerprint,
        snapshot_digest,
        snapshot,
    )


if __name__ == "__main__":
    raise SystemExit(main())
