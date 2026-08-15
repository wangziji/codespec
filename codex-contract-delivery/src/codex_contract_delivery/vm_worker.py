"""Lima-backed isolated worker execution."""

from __future__ import annotations

import base64
import binascii
import errno
import fcntl
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .canonical import canonical_digest
from .worker import WorkerKind, WorkerLauncher, WorkerTask, WorkerViolation


@dataclass(frozen=True)
class LimaWorkerConfig:
    limactl_executable: Path
    instance: str
    readonly_source_root: Path
    guest_workspace_root: Path
    guest_python: Path
    guest_runner: Path
    host_staging_root: Path

    def __post_init__(self) -> None:
        executable = Path(self.limactl_executable)
        source = Path(self.readonly_source_root)
        runner = Path(self.guest_runner)
        staging = Path(self.host_staging_root)
        if not executable.is_absolute() or not executable.is_file():
            raise WorkerViolation(
                "limactl executable must be an existing absolute file"
            )
        if not os.access(executable, os.X_OK):
            raise WorkerViolation("limactl executable is not executable")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.instance) is None:
            raise WorkerViolation("Lima instance name is unsafe")
        for name, value in (
            ("readonly_source_root", source),
            ("guest_workspace_root", Path(self.guest_workspace_root)),
            ("guest_python", Path(self.guest_python)),
            ("guest_runner", runner),
            ("host_staging_root", staging),
        ):
            if not value.is_absolute():
                raise WorkerViolation(f"{name} must be absolute")
        try:
            runner.relative_to(source)
        except ValueError as error:
            raise WorkerViolation(
                "guest runner must be on the readonly source mount"
            ) from error
        if not runner.is_file():
            raise WorkerViolation("guest runner does not exist")
        source_real = source.resolve(strict=True)
        staging.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging_real = staging.resolve(strict=True)
        if staging_real.is_relative_to(source_real):
            raise WorkerViolation(
                "host staging root must be outside the approved source"
            )
        details = staging_real.stat()
        if details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise WorkerViolation("host staging root ownership or mode is unsafe")
        object.__setattr__(self, "limactl_executable", executable.resolve(strict=True))
        object.__setattr__(self, "readonly_source_root", source_real)
        object.__setattr__(self, "guest_runner", runner.resolve(strict=True))
        object.__setattr__(self, "host_staging_root", staging_real)


@dataclass(frozen=True)
class PreparedExport:
    stage_ref: str
    stage_digest: str
    effect_id: str
    fence: int
    task_fingerprint: str
    declared_paths: tuple[str, ...]
    before_manifest: tuple[tuple[str, str], ...]
    after_manifest: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SourceSnapshot:
    digest: str
    archive: bytes


def _open_directory_beneath(root: Path, parts: tuple[str, ...]) -> int:
    descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        for part in parts:
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_regular_beneath(root: Path, candidate: Path) -> int:
    parent = _open_directory_beneath(root, candidate.parts[:-1])
    try:
        return os.open(
            candidate.name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)


def _read_link_beneath(root: Path, candidate: Path) -> tuple[os.stat_result, str]:
    parent = _open_directory_beneath(root, candidate.parts[:-1])
    try:
        details = os.stat(candidate.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISLNK(details.st_mode):
            raise WorkerViolation("tracked symlink identity drifted")
        return details, os.readlink(candidate.name, dir_fd=parent)
    finally:
        os.close(parent)


def create_source_snapshot(source: Path) -> SourceSnapshot:
    """Build a deterministic, tracked-only snapshot without exposing git metadata."""
    completed = subprocess.run(
        ("git", "-C", str(source), "ls-files", "--cached", "--stage", "-z"),
        shell=False,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WorkerViolation("approved source cannot produce a tracked snapshot")
    entries: list[tuple[str, Path, str]] = []
    modes: dict[str, str] = {}
    for raw_entry in completed.stdout.split(b"\x00"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, _object_id, stage = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as error:
            raise WorkerViolation("tracked source manifest is malformed") from error
        candidate = Path(relative)
        if (
            mode not in {"100644", "100755", "120000"}
            or stage != "0"
            or candidate.is_absolute()
            or ".." in candidate.parts
            or not relative
            or candidate.parts[0] == ".codex"
            or candidate.name == ".mcp.json"
            or relative in modes
        ):
            raise WorkerViolation("tracked source contains an unsupported entry")
        entries.append((relative, candidate, mode))
        modes[relative] = mode
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for relative, candidate, mode in entries:
            link_before: os.stat_result | None = None
            link_target: str | None = None
            if mode == "120000":
                link_before, link_target = _read_link_beneath(source, candidate)
                target = Path(link_target)
                if target.is_absolute() or ".." in target.parts:
                    raise WorkerViolation(
                        "tracked source contains a symlink or path escape"
                    )
                target_relative = (candidate.parent / target).as_posix()
                target_mode = modes.get(target_relative)
                if target_mode not in {"100644", "100755"}:
                    raise WorkerViolation(
                        "tracked symlink target is not a tracked regular file"
                    )
                mode = target_mode
                source_candidate = Path(target_relative)
            else:
                source_candidate = candidate
            descriptor = _open_regular_beneath(source, source_candidate)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode):
                    raise WorkerViolation(
                        "tracked source contains a symlink or path escape"
                    )
                info = tarfile.TarInfo(candidate.as_posix())
                info.size = before.st_size
                info.mode = 0o755 if mode == "100755" else 0o644
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with os.fdopen(os.dup(descriptor), "rb") as stream:
                    archive.addfile(info, stream)
                after = os.fstat(descriptor)
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise WorkerViolation("tracked source changed during snapshot")
                if link_before is not None:
                    current_link, current_target = _read_link_beneath(source, candidate)
                    if current_link != link_before or current_target != link_target:
                        raise WorkerViolation("tracked symlink changed during snapshot")
            finally:
                os.close(descriptor)
    value = output.getvalue()
    return SourceSnapshot(sha256(value).hexdigest(), value)


class LimaWorkerBackend:
    def __init__(self, config: LimaWorkerConfig) -> None:
        self.config = config
        self._source_snapshots: dict[str, SourceSnapshot] = {}
        self._task_authorities: dict[str, str] = {}
        original_identity = self._identity(config.limactl_executable)
        authority_root = config.host_staging_root / "authority"
        authority_root.mkdir(mode=0o700, exist_ok=True)
        authority_root.chmod(0o700)
        authority_version = authority_root / str(original_identity["sha256"])
        authority_version.mkdir(mode=0o700, exist_ok=True)
        control_executable = authority_version / "limactl"
        if not control_executable.exists():
            temporary = authority_version / f".limactl.{os.getpid()}.tmp"
            shutil.copyfile(config.limactl_executable, temporary, follow_symlinks=False)
            temporary.chmod(0o500)
            try:
                os.rename(temporary, control_executable)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        copied_identity = self._identity(control_executable)
        if (
            copied_identity["sha256"] != original_identity["sha256"]
            or copied_identity["size"] != original_identity["size"]
        ):
            raise WorkerViolation("immutable Lima control executable drifted")
        self._control_executable = control_executable

    @staticmethod
    def _identity(path: Path) -> dict[str, object]:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise WorkerViolation("worker authority executable is not regular")
            digest = sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            return {
                "device": details.st_dev,
                "inode": details.st_ino,
                "mode": details.st_mode,
                "size": details.st_size,
                "mtime_ns": details.st_mtime_ns,
                "sha256": digest.hexdigest(),
            }
        finally:
            os.close(descriptor)

    def _lima_authority_digest(self) -> str:
        completed = subprocess.run(
            (
                str(self._control_executable),
                "list",
                self.config.instance,
                "--json",
            ),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            raise WorkerViolation("Lima authority probe failed closed")
        try:
            record = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise WorkerViolation("Lima authority probe is malformed") from error
        if (
            not isinstance(record, dict)
            or record.get("name") != self.config.instance
            or record.get("status") != "Running"
            or not isinstance(record.get("config"), dict)
        ):
            raise WorkerViolation("Lima instance authority drifted")
        instance_config = record["config"]
        mounts = instance_config.get("mounts")
        if not isinstance(mounts, list):
            raise WorkerViolation("Lima mount authority is unavailable")
        approved_mount: dict[str, object] | None = None
        for raw_mount in mounts:
            if not isinstance(raw_mount, dict):
                raise WorkerViolation("Lima mount authority is malformed")
            location = raw_mount.get("location")
            if not isinstance(location, str):
                continue
            try:
                mount_path = Path(location).resolve(strict=True)
                self.config.readonly_source_root.relative_to(mount_path)
            except (OSError, ValueError):
                continue
            sshfs = raw_mount.get("sshfs")
            if (
                raw_mount.get("writable") is not False
                or not isinstance(sshfs, dict)
                or sshfs.get("followSymlinks") is not False
            ):
                raise WorkerViolation("Lima approved mount is not read-only")
            if approved_mount is not None:
                raise WorkerViolation("Lima approved mount authority is ambiguous")
            approved_mount = raw_mount
        ssh = instance_config.get("ssh")
        if approved_mount is None or not isinstance(ssh, dict):
            raise WorkerViolation("Lima approved mount authority is unavailable")
        if any(
            ssh.get(name) is not False
            for name in ("loadDotSSHPubKeys", "forwardAgent", "forwardX11")
        ):
            raise WorkerViolation("Lima credential forwarding is forbidden")
        guest_probe = subprocess.run(
            (
                str(self._control_executable),
                "shell",
                self.config.instance,
                "--",
                str(self.config.guest_python),
                str(self.config.guest_runner),
                "--attest",
                "--json",
            ),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if guest_probe.returncode != 0:
            raise WorkerViolation("guest runtime attestation failed closed")
        try:
            guest_authority = json.loads(guest_probe.stdout)
        except json.JSONDecodeError as error:
            raise WorkerViolation("guest runtime attestation is malformed") from error
        if (
            not isinstance(guest_authority, dict)
            or guest_authority.get("type") != "cdd.vm.attestation"
            or guest_authority.get("schema_version") != "1.0"
            or guest_authority.get("codex_version") != "0.147.0"
            or guest_authority.get("runner_mount_readonly") is not True
            or guest_authority.get("sandbox_prerequisites") is not True
        ):
            raise WorkerViolation("guest runtime authority drifted")
        runner_identity = guest_authority.get("runner")
        python_identity = guest_authority.get("python")
        codex_identity = guest_authority.get("codex")
        if any(
            not isinstance(identity, dict)
            or not isinstance(identity.get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", identity["sha256"]) is None
            for identity in (runner_identity, python_identity, codex_identity)
        ):
            raise WorkerViolation("guest executable identity is malformed")
        local_runner_identity = self._identity(self.config.guest_runner)
        if runner_identity["sha256"] != local_runner_identity["sha256"]:
            raise WorkerViolation(
                "guest runner identity differs from readonly artifact"
            )
        authority = {
            "schema_version": "1.0",
            "instance": self.config.instance,
            "vm_type": record.get("vmType"),
            "arch": record.get("arch"),
            "lima_version": record.get("limaVersion"),
            "mount": approved_mount,
            "guest_workspace_root": str(self.config.guest_workspace_root),
            "guest_python": str(self.config.guest_python),
            "guest_runner": str(self.config.guest_runner),
            "runner_identity": local_runner_identity,
            "limactl_identity": self._identity(self.config.limactl_executable),
            "control_executable_identity": self._identity(self._control_executable),
            "codex_version": "0.147.0",
            "ssh": {
                name: ssh.get(name)
                for name in (
                    "loadDotSSHPubKeys",
                    "forwardAgent",
                    "forwardX11",
                    "forwardX11Trusted",
                )
            },
            "guest_runtime": guest_authority,
        }
        return canonical_digest(authority)

    @contextmanager
    def _root_lock(self, root: Path) -> Iterator[None]:
        locks = self.config.host_staging_root / "locks"
        locks.mkdir(mode=0o700, exist_ok=True)
        locks.chmod(0o700)
        lock_name = sha256(str(root.resolve(strict=True)).encode("utf-8")).hexdigest()
        descriptor = os.open(
            locks / f"{lock_name}.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def canonical_command(self, task: WorkerTask) -> tuple[str, ...]:
        source = task.approved_root.resolve(strict=True)
        try:
            source.relative_to(self.config.readonly_source_root)
        except ValueError as error:
            raise WorkerViolation(
                "approved root is outside the readonly VM mount"
            ) from error
        snapshot = create_source_snapshot(source)
        self._source_snapshots[task.fingerprint()] = snapshot
        authority_digest = self._lima_authority_digest()
        self._task_authorities[task.fingerprint()] = authority_digest
        return (
            str(self._control_executable),
            "shell",
            self.config.instance,
            "--",
            str(self.config.guest_python),
            str(self.config.guest_runner),
            "--workspace-base",
            str(self.config.guest_workspace_root),
            "--authority-digest",
            authority_digest,
            "--source-snapshot-digest",
            snapshot.digest,
            "--kind",
            task.kind.value,
            "--task-fingerprint",
            task.fingerprint(),
            "--json",
        )

    def request_payload(self, task: WorkerTask) -> dict[str, str]:
        expected = self._source_snapshots.get(task.fingerprint())
        current = create_source_snapshot(task.approved_root.resolve(strict=True))
        if expected is None or current.digest != expected.digest:
            raise WorkerViolation("tracked source snapshot drifted after authorization")
        return {
            "source_snapshot_sha256": current.digest,
            "source_snapshot_b64": base64.b64encode(current.archive).decode("ascii"),
        }

    def cancel(
        self,
        task: WorkerTask,
        effect_id: str,
        task_fingerprint: str,
        fence: int,
    ) -> None:
        if task_fingerprint != task.fingerprint():
            raise WorkerViolation("remote cancellation task fingerprint drifted")
        expected_authority = self._task_authorities.get(task_fingerprint)
        current_authority = self._lima_authority_digest()
        if expected_authority is None or current_authority != expected_authority:
            raise WorkerViolation("remote cancellation authority drifted")
        command = (
            str(self._control_executable),
            "shell",
            self.config.instance,
            "--",
            str(self.config.guest_python),
            str(self.config.guest_runner),
            "--workspace-base",
            str(self.config.guest_workspace_root),
            "--authority-digest",
            current_authority,
            "--cancel-effect",
            effect_id,
            "--cancel-task-fingerprint",
            task_fingerprint,
            "--cancel-fence",
            str(fence),
            "--json",
        )
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            raise WorkerViolation("remote worker cancellation failed closed")

    @staticmethod
    def _result_record(stdout: str) -> dict[str, object]:
        records: list[dict[str, object]] = []
        for line in stdout.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("type") == "cdd.vm.result":
                records.append(record)
        if len(records) != 1:
            raise WorkerViolation("guest returned an ambiguous result envelope")
        record = records[0]
        if (
            set(record)
            != {
                "type",
                "schema_version",
                "task_fingerprint",
                "patch_sha256",
                "patch_b64",
                "name_status_b64",
            }
            or record.get("schema_version") != "1.0"
        ):
            raise WorkerViolation("guest result envelope is structurally unknown")
        return record

    @staticmethod
    def _decode_field(record: dict[str, object], name: str) -> bytes:
        value = record[name]
        if not isinstance(value, str):
            raise WorkerViolation(f"guest {name} must be base64 text")
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise WorkerViolation(f"guest {name} is not valid base64") from error

    @staticmethod
    def _name_status_paths(value: bytes) -> tuple[str, ...]:
        fields = value.split(b"\x00")
        if fields and fields[-1] == b"":
            fields.pop()
        paths: list[str] = []
        index = 0
        try:
            while index < len(fields):
                code = fields[index].decode("ascii")
                index += 1
                path_count = 2 if code.startswith(("R", "C")) else 1
                if not re.fullmatch(r"(?:[ACDMRTUXB]|[RC][0-9]{1,3})", code):
                    raise WorkerViolation("guest name-status contains an unknown code")
                for _ in range(path_count):
                    path = fields[index].decode("utf-8")
                    index += 1
                    paths.append(path)
        except (IndexError, UnicodeDecodeError) as error:
            raise WorkerViolation("guest name-status is malformed") from error
        if not paths:
            return ()
        return tuple(dict.fromkeys(paths))

    @staticmethod
    def _path_allowed(path: str, allowed: tuple[str, ...]) -> bool:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts or not path:
            return False
        return any(
            root == "." or path == root or path.startswith(root.rstrip("/") + "/")
            for root in allowed
        )

    @staticmethod
    def _git_apply(
        root: Path, patch: bytes, *arguments: str
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ("git", "-C", str(root), "apply", *arguments, "-"),
            input=patch,
            shell=False,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def _file_manifest(root: Path) -> dict[str, str]:
        return {
            path: signature
            for path, signature in WorkerLauncher._manifest(root, skip_root_git=True)
            if not signature.startswith("dir:")
        }

    @classmethod
    def _validate_patch_in_copy(
        cls,
        root: Path,
        patch: bytes,
        declared_paths: tuple[str, ...],
        allowed_paths: tuple[str, ...],
    ) -> tuple[dict[str, str], dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix="cdd-patch-check-") as directory:
            candidate = Path(directory) / "worktree"
            shutil.copytree(
                root,
                candidate,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
            before = cls._file_manifest(candidate)
            applied = cls._git_apply(candidate, patch, "--binary")
            if applied.returncode != 0:
                raise WorkerViolation(
                    "guest patch does not apply to approved host state"
                )
            after = cls._file_manifest(candidate)
            actual_paths = tuple(
                sorted(
                    path
                    for path in before.keys() | after.keys()
                    if before.get(path) != after.get(path)
                )
            )
            if actual_paths != tuple(sorted(declared_paths)):
                raise WorkerViolation("guest patch and name-status disagree")
            if any(
                path == ".git"
                or path.startswith(".git/")
                or not cls._path_allowed(path, allowed_paths)
                for path in actual_paths
            ):
                raise WorkerViolation("guest patch exceeds approved paths")
            if any(
                signature.startswith("link:")
                for path, signature in after.items()
                if path in actual_paths
            ):
                raise WorkerViolation("guest patch cannot create a symlink")
            return before, after

    @staticmethod
    def _write_stage_file(path: Path, value: bytes) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
        try:
            offset = 0
            while offset < len(value):
                offset += os.write(descriptor, value[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _persist_stage(
        self,
        digest: str,
        metadata: dict[str, object],
        patch: bytes,
    ) -> Path:
        target = self.config.host_staging_root / digest
        temporary = Path(
            tempfile.mkdtemp(prefix=".stage-", dir=self.config.host_staging_root)
        )
        try:
            self._write_stage_file(temporary / "patch.bin", patch)
            self._write_stage_file(
                temporary / "metadata.json",
                json.dumps(
                    metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            self._fsync_directory(temporary)
            try:
                os.rename(temporary, target)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
            else:
                target.chmod(0o500)
            self._fsync_directory(self.config.host_staging_root)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return target

    def _load_stage(self, prepared: PreparedExport) -> tuple[bytes, dict[str, object]]:
        directory = self.config.host_staging_root / prepared.stage_digest
        if directory.is_symlink() or directory.resolve(strict=True) != directory:
            raise WorkerViolation("prepared export stage path drifted")
        directory_details = directory.lstat()
        if (
            directory_details.st_uid != os.getuid()
            or not stat.S_ISDIR(directory_details.st_mode)
            or directory_details.st_mode & 0o277
        ):
            raise WorkerViolation("prepared export stage ownership or mode drifted")
        patch_path = directory / "patch.bin"
        metadata_path = directory / "metadata.json"
        for path in (patch_path, metadata_path):
            details = path.lstat()
            if (
                not path.is_file()
                or path.is_symlink()
                or details.st_uid != os.getuid()
                or details.st_mode & 0o377
            ):
                raise WorkerViolation("prepared export stage identity drifted")
        patch = patch_path.read_bytes()
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkerViolation("prepared export metadata is malformed") from error
        if not isinstance(metadata, dict) or canonical_digest(metadata) != (
            prepared.stage_digest
        ):
            raise WorkerViolation("prepared export metadata digest drifted")
        if metadata.get("patch_sha256") != sha256(patch).hexdigest():
            raise WorkerViolation("prepared export patch digest drifted")
        expected_metadata = {
            "schema_version": "1.0",
            "effect_id": prepared.effect_id,
            "fence": prepared.fence,
            "task_fingerprint": prepared.task_fingerprint,
            "approved_root": metadata.get("approved_root"),
            "patch_sha256": sha256(patch).hexdigest(),
            "declared_paths": list(prepared.declared_paths),
            "before_manifest": [list(item) for item in prepared.before_manifest],
            "after_manifest": [list(item) for item in prepared.after_manifest],
        }
        if metadata != expected_metadata or prepared.stage_ref != (
            f"effect-stage://sha256/{prepared.stage_digest}"
        ):
            raise WorkerViolation("prepared export bound metadata drifted")
        return patch, metadata

    def prepare_export(
        self,
        task: WorkerTask,
        stdout: str,
        effect_id: str,
        fence: int,
    ) -> tuple[str, object]:
        record = self._result_record(stdout)
        if record["task_fingerprint"] != task.fingerprint():
            raise WorkerViolation("guest task fingerprint does not match")
        patch = self._decode_field(record, "patch_b64")
        name_status = self._decode_field(record, "name_status_b64")
        if record["patch_sha256"] != sha256(patch).hexdigest():
            raise WorkerViolation("guest patch digest does not match")
        paths = self._name_status_paths(name_status)
        if any(not self._path_allowed(path, task.allowed_paths) for path in paths):
            raise WorkerViolation("guest patch exceeds approved paths")
        if b"new file mode 120000\n" in patch or b"new mode 120000\n" in patch:
            raise WorkerViolation("guest patch cannot create a symlink")
        if task.kind is WorkerKind.ANALYSIS and (patch or paths):
            raise WorkerViolation("analysis guest returned a write patch")
        if bool(patch) != bool(paths):
            raise WorkerViolation("guest patch and name-status disagree")
        root = task.approved_root.resolve(strict=True)
        if self.config.host_staging_root.is_relative_to(root):
            raise WorkerViolation(
                "prepared export stage cannot be inside approved root"
            )
        with self._root_lock(root):
            if patch:
                before, after = self._validate_patch_in_copy(
                    root,
                    patch,
                    paths,
                    task.allowed_paths,
                )
            else:
                before = self._file_manifest(root)
                after = dict(before)
            metadata: dict[str, object] = {
                "schema_version": "1.0",
                "effect_id": effect_id,
                "fence": fence,
                "task_fingerprint": task.fingerprint(),
                "approved_root": str(root),
                "patch_sha256": sha256(patch).hexdigest(),
                "declared_paths": sorted(paths),
                "before_manifest": sorted(before.items()),
                "after_manifest": sorted(after.items()),
            }
            stage_digest = canonical_digest(metadata)
            stage_ref = f"effect-stage://sha256/{stage_digest}"
            self._persist_stage(stage_digest, metadata, patch)
            prepared = PreparedExport(
                stage_ref,
                stage_digest,
                effect_id,
                fence,
                task.fingerprint(),
                tuple(sorted(paths)),
                tuple(sorted(before.items())),
                tuple(sorted(after.items())),
            )
            self._load_stage(prepared)
            return stage_ref, prepared

    def commit_export(
        self,
        task: WorkerTask,
        prepared: object,
        authority_check: Callable[[], None],
    ) -> tuple[str, ...]:
        if not isinstance(prepared, PreparedExport):
            raise WorkerViolation("prepared export has an unknown type")
        if prepared.task_fingerprint != task.fingerprint():
            raise WorkerViolation("prepared export task fingerprint drifted")
        root = task.approved_root.resolve(strict=True)
        before = dict(prepared.before_manifest)
        expected_after = dict(prepared.after_manifest)
        with self._root_lock(root):
            authority_check()
            patch, metadata = self._load_stage(prepared)
            if (
                metadata.get("effect_id") != prepared.effect_id
                or metadata.get("fence") != prepared.fence
                or metadata.get("approved_root") != str(root)
            ):
                raise WorkerViolation("prepared export authority metadata drifted")
            current = self._file_manifest(root)
            if current == expected_after:
                return prepared.declared_paths
            if current != before:
                raise WorkerViolation("prepared export host state is mixed or drifted")
            checked = self._git_apply(root, patch, "--check", "--binary")
            if checked.returncode != 0:
                raise WorkerViolation("prepared export no longer applies to host state")
            applied = self._git_apply(root, patch, "--binary")
            observed = self._file_manifest(root)
            if applied.returncode == 0 and observed == expected_after:
                return prepared.declared_paths
            if observed == before:
                raise WorkerViolation(
                    "prepared export application failed before mutation"
                )
            if patch:
                self._git_apply(root, patch, "--reverse", "--binary")
            rolled_back = self._file_manifest(root)
            if rolled_back == before:
                raise WorkerViolation(
                    "prepared export partially applied and was rolled back"
                )
            raise WorkerViolation("prepared export left a mixed host state")

    def adopt_export(self, prepared: PreparedExport, fence: int) -> PreparedExport:
        """Re-attest and content-address the same stage for a new live fence."""
        if not isinstance(fence, int) or isinstance(fence, bool) or fence <= 0:
            raise WorkerViolation("prepared adoption fence is invalid")
        patch, metadata = self._load_stage(prepared)
        adopted_metadata = dict(metadata)
        adopted_metadata["fence"] = fence
        digest = canonical_digest(adopted_metadata)
        self._persist_stage(digest, adopted_metadata, patch)
        adopted = PreparedExport(
            f"effect-stage://sha256/{digest}",
            digest,
            prepared.effect_id,
            fence,
            prepared.task_fingerprint,
            prepared.declared_paths,
            prepared.before_manifest,
            prepared.after_manifest,
        )
        self._load_stage(adopted)
        return adopted
