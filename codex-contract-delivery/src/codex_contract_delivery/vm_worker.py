"""Lima-backed isolated worker execution."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .worker import WorkerKind, WorkerLauncher, WorkerTask, WorkerViolation


@dataclass(frozen=True)
class LimaWorkerConfig:
    limactl_executable: Path
    instance: str
    readonly_source_root: Path
    guest_workspace_root: Path
    guest_python: Path
    guest_runner: Path

    def __post_init__(self) -> None:
        executable = Path(self.limactl_executable)
        source = Path(self.readonly_source_root)
        runner = Path(self.guest_runner)
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
        object.__setattr__(self, "limactl_executable", executable.resolve(strict=True))
        object.__setattr__(self, "readonly_source_root", source.resolve(strict=True))
        object.__setattr__(self, "guest_runner", runner.resolve(strict=True))


class LimaWorkerBackend:
    def __init__(self, config: LimaWorkerConfig) -> None:
        self.config = config

    def canonical_command(self, task: WorkerTask) -> tuple[str, ...]:
        source = task.approved_root.resolve(strict=True)
        try:
            source.relative_to(self.config.readonly_source_root)
        except ValueError as error:
            raise WorkerViolation(
                "approved root is outside the readonly VM mount"
            ) from error
        return (
            str(self.config.limactl_executable),
            "shell",
            self.config.instance,
            "--",
            str(self.config.guest_python),
            str(self.config.guest_runner),
            "--workspace-base",
            str(self.config.guest_workspace_root),
            "--source-root",
            str(source),
            "--kind",
            task.kind.value,
            "--task-fingerprint",
            task.fingerprint(),
            "--json",
        )

    def cancel(
        self,
        task: WorkerTask,
        effect_id: str,
        task_fingerprint: str,
    ) -> None:
        if task_fingerprint != task.fingerprint():
            raise WorkerViolation("remote cancellation task fingerprint drifted")
        command = (
            str(self.config.limactl_executable),
            "shell",
            self.config.instance,
            "--",
            str(self.config.guest_python),
            str(self.config.guest_runner),
            "--workspace-base",
            str(self.config.guest_workspace_root),
            "--cancel-effect",
            effect_id,
            "--cancel-task-fingerprint",
            task_fingerprint,
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
    ) -> None:
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

    def apply_export(self, task: WorkerTask, stdout: str) -> tuple[str, ...]:
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
        if task.kind is WorkerKind.ANALYSIS:
            if patch or paths:
                raise WorkerViolation("analysis guest returned a write patch")
            return ()
        if bool(patch) != bool(paths):
            raise WorkerViolation("guest patch and name-status disagree")
        if not patch:
            return ()
        self._validate_patch_in_copy(
            task.approved_root,
            patch,
            paths,
            task.allowed_paths,
        )
        checked = self._git_apply(task.approved_root, patch, "--check", "--binary")
        if checked.returncode != 0:
            raise WorkerViolation("guest patch does not apply to approved host state")
        applied = self._git_apply(task.approved_root, patch, "--binary")
        if applied.returncode != 0:
            raise WorkerViolation("guest patch application failed")
        return tuple(sorted(paths))
