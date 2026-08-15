"""Codex worker command construction and git-bound write verification."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from .canonical import canonical_digest
from .capabilities import CapabilityBroker, DispatchStatus, EffectResult, Grant


class WorkerViolation(RuntimeError):
    """A worker task or observed filesystem result exceeded its grant."""


class WorkerKind(str, Enum):
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"


@dataclass(frozen=True)
class WorkerTask:
    kind: WorkerKind
    approved_root: Path
    approved_context: str
    allowed_paths: tuple[str, ...] = (".",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", WorkerKind(self.kind))
        object.__setattr__(self, "approved_root", Path(self.approved_root))
        if (
            not isinstance(self.approved_context, str)
            or not self.approved_context.strip()
        ):
            raise ValueError("approved_context must be a non-empty string")
        if "\x00" in self.approved_context:
            raise ValueError("approved_context cannot contain NUL")
        if isinstance(self.allowed_paths, str | bytes) or not self.allowed_paths:
            raise ValueError("allowed_paths must be a non-empty sequence")
        normalized: list[str] = []
        for item in self.allowed_paths:
            if not isinstance(item, str) or not item or "\x00" in item:
                raise ValueError("allowed_paths must contain non-empty strings")
            candidate = Path(item)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError("allowed_paths must stay relative to approved_root")
            value = candidate.as_posix().rstrip("/") or "."
            if value in normalized:
                raise ValueError("allowed_paths cannot contain duplicates")
            normalized.append(value)
        object.__setattr__(self, "allowed_paths", tuple(normalized))

    def fingerprint(self) -> str:
        return canonical_digest(
            {
                "kind": self.kind.value,
                "approved_root": str(self.approved_root.resolve(strict=False)),
                "approved_context_digest": canonical_digest(self.approved_context),
                "allowed_paths": self.allowed_paths,
            }
        )


@dataclass(frozen=True)
class _GitSnapshot:
    diff: str
    name_status: str
    changed_paths: tuple[str, ...]
    worktree_manifest: tuple[tuple[str, str], ...]
    git_metadata_manifest: tuple[tuple[str, str], ...]
    submodule_status: str


@dataclass(frozen=True)
class WorkerResult:
    effect: EffectResult
    before_diff: str
    before_name_status: str
    after_diff: str
    after_name_status: str
    changed_paths: tuple[str, ...]


_BROKER_OWNED = ("github", "penpot", "deploy", "secret", "prod")


class WorkerBackend(Protocol):
    def canonical_command(self, task: WorkerTask) -> tuple[str, ...]: ...

    def request_payload(self, task: WorkerTask) -> dict[str, str]: ...

    def prepare_export(
        self,
        task: WorkerTask,
        stdout: str,
        effect_id: str,
        fence: int,
    ) -> tuple[str, object]: ...

    def commit_export(
        self,
        task: WorkerTask,
        prepared: object,
        authority_check: Callable[[], None],
    ) -> tuple[str, ...]: ...

    def adopt_export(self, prepared: object, fence: int) -> object: ...

    def cancel(
        self,
        task: WorkerTask,
        effect_id: str,
        task_fingerprint: str,
        fence: int,
    ) -> None: ...


class WorkerLauncher:
    """Launch only controller-scoped Codex workers in an approved real git root."""

    def __init__(
        self,
        broker: CapabilityBroker,
        *,
        codex_executable: str | None = None,
        backend: WorkerBackend | None = None,
    ) -> None:
        self.broker = broker
        if (codex_executable is None) == (backend is None):
            raise WorkerViolation(
                "configure exactly one local Codex executable or isolated backend"
            )
        self.backend = backend
        if codex_executable is None:
            self.codex_executable = None
            return
        try:
            self.codex_executable = str(Path(codex_executable).resolve(strict=True))
        except OSError as error:
            raise WorkerViolation("Codex executable does not exist") from error
        if not os.access(self.codex_executable, os.X_OK):
            raise WorkerViolation("Codex executable is not executable")

    @staticmethod
    def _real_root(task: WorkerTask) -> Path:
        raw = task.approved_root
        if not raw.is_absolute():
            raise WorkerViolation("approved root must be absolute")
        lexical = Path(os.path.abspath(raw))
        try:
            real = raw.resolve(strict=True)
        except OSError as error:
            raise WorkerViolation("approved root does not exist") from error
        if lexical != real:
            raise WorkerViolation("approved root cannot be a symlink")
        return real

    @staticmethod
    def _git(root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(root), *arguments),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise WorkerViolation("approved root must be a git worktree")
        return completed.stdout

    def _validate_root(self, task: WorkerTask, grant: Grant) -> Path:
        root = self._real_root(task)
        top = Path(self._git(root, "rev-parse", "--show-toplevel").strip()).resolve()
        if top != root:
            raise WorkerViolation("approved root must be the git worktree root")
        if task.kind is WorkerKind.IMPLEMENTATION and not (root / ".git").is_file():
            raise WorkerViolation(
                "implementation root must be an isolated linked git worktree"
            )
        if grant.resource != str(root):
            raise WorkerViolation("worker root does not match granted resource")
        if task.kind is WorkerKind.IMPLEMENTATION and not any(
            root == Path(item) or root.is_relative_to(Path(item))
            for item in grant.allowed_write_roots
        ):
            raise WorkerViolation("worker root is outside granted write scope")
        if self.backend is None:
            self._reject_symlinks(root)
        return root

    @staticmethod
    def _reject_symlinks(root: Path) -> None:
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            current = Path(directory)
            for name in (*directory_names, *file_names):
                candidate = current / name
                if candidate.is_symlink():
                    raise WorkerViolation("approved worktree cannot contain a symlink")

    @staticmethod
    def _parse_status(status: str) -> tuple[str, ...]:
        entries = status.split("\x00")
        paths: set[str] = set()
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            if len(entry) < 4:
                raise WorkerViolation("git returned malformed name-status data")
            code = entry[:2]
            paths.add(entry[3:])
            if "R" in code or "C" in code:
                if index >= len(entries) or not entries[index]:
                    raise WorkerViolation("git returned malformed rename data")
                paths.add(entries[index])
                index += 1
        return tuple(sorted(paths))

    def _snapshot(self, root: Path) -> _GitSnapshot:
        diff = self._git(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
        status = self._git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
        )
        git_dir = Path(
            self._git(root, "rev-parse", "--path-format=absolute", "--git-dir").strip()
        )
        common_dir = Path(
            self._git(
                root, "rev-parse", "--path-format=absolute", "--git-common-dir"
            ).strip()
        )
        metadata_paths = tuple(
            dict.fromkeys(
                common_dir / name
                for name in ("HEAD", "index", "config", "hooks", "refs", "worktrees")
            )
        ) + tuple(
            path
            for path in (git_dir / "HEAD", git_dir / "index")
            if path not in {common_dir / "HEAD", common_dir / "index"}
        )
        submodules = self._git(root, "submodule", "status", "--recursive")
        return _GitSnapshot(
            diff,
            status,
            self._parse_status(status),
            self._manifest(root, skip_root_git=True),
            self._manifest_many(metadata_paths),
            submodules,
        )

    @staticmethod
    def _path_signature(path: Path) -> str:
        details = path.lstat()
        mode = stat.S_IMODE(details.st_mode)
        if path.is_symlink():
            return f"link:{mode:o}:{os.readlink(path)}"
        if path.is_dir():
            return f"dir:{mode:o}"
        if path.is_file():
            digest = sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            return f"file:{mode:o}:{details.st_size}:{digest.hexdigest()}"
        return f"other:{details.st_mode:o}:{details.st_size}"

    @classmethod
    def _manifest(
        cls, root: Path, *, skip_root_git: bool = False
    ) -> tuple[tuple[str, str], ...]:
        if not root.exists() and not root.is_symlink():
            return ()
        entries: list[tuple[str, str]] = []
        if not root.is_dir() or root.is_symlink():
            return ((root.name, cls._path_signature(root)),)
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            current = Path(directory)
            for name in sorted((*directory_names, *file_names)):
                candidate = current / name
                relative = candidate.relative_to(root).as_posix()
                if skip_root_git and relative == ".git":
                    if candidate in [current / item for item in directory_names]:
                        directory_names.remove(name)
                    continue
                entries.append((relative, cls._path_signature(candidate)))
        return tuple(sorted(entries))

    @classmethod
    def _manifest_many(cls, roots: tuple[Path, ...]) -> tuple[tuple[str, str], ...]:
        entries: list[tuple[str, str]] = []
        for root in roots:
            if not root.exists() and not root.is_symlink():
                continue
            if root.is_dir() and not root.is_symlink():
                entries.extend(
                    (f"{root}:{relative}", signature)
                    for relative, signature in cls._manifest(root)
                )
            else:
                entries.append((str(root), cls._path_signature(root)))
        return tuple(sorted(entries))

    @staticmethod
    def _delta_paths(before: _GitSnapshot, after: _GitSnapshot) -> tuple[str, ...]:
        old = dict(before.worktree_manifest)
        new = dict(after.worktree_manifest)
        return tuple(
            sorted(
                path
                for path in old.keys() | new.keys()
                if old.get(path) != new.get(path)
            )
        )

    @staticmethod
    def _validate_changed_paths(root: Path, paths: tuple[str, ...]) -> None:
        for relative in paths:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise WorkerViolation("worker changed a path outside the approved root")
            target = root / candidate
            if target.is_symlink():
                raise WorkerViolation("worker created or changed a symlink")
            resolved = target.resolve(strict=False)
            if not resolved.is_relative_to(root):
                raise WorkerViolation("worker changed a path outside the approved root")

    @staticmethod
    def canonical_command(task: WorkerTask, codex_executable: str) -> tuple[str, ...]:
        return (
            str(Path(codex_executable).resolve(strict=True)),
            "exec",
            "--sandbox",
            "read-only" if task.kind is WorkerKind.ANALYSIS else "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--cd",
            str(task.approved_root.resolve(strict=True)),
            "--json",
            "-",
        )

    def build_command(self, task: WorkerTask, grant: Grant) -> tuple[str, ...]:
        if any(part in grant.capability.lower() for part in _BROKER_OWNED):
            raise WorkerViolation(
                "broker-owned capability cannot be delegated to a worker"
            )
        expected = f"worker.{task.kind.value}"
        if grant.capability != expected:
            raise WorkerViolation("worker kind does not match the granted capability")
        expected_operation = "read" if task.kind is WorkerKind.ANALYSIS else "write"
        if grant.operation != expected_operation:
            raise WorkerViolation("worker operation does not match its sandbox")
        self._validate_root(task, grant)
        command = (
            self.backend.canonical_command(task)
            if self.backend is not None
            else self.canonical_command(task, str(self.codex_executable))
        )
        if task.fingerprint() != grant.task_fingerprint:
            raise WorkerViolation("worker task fingerprint does not match the grant")
        if command != grant.canonical_argv:
            raise WorkerViolation("worker command does not exactly match the grant")
        return grant.canonical_argv

    def run(self, task: WorkerTask, grant: Grant) -> WorkerResult:
        root = self._validate_root(task, grant)
        command = self.build_command(task, grant)
        before = self._snapshot(root)

        def validated_snapshot(exported_paths: tuple[str, ...]) -> _GitSnapshot:
            after = self._snapshot(root)
            delta_paths = self._delta_paths(before, after)
            self._validate_changed_paths(root, delta_paths)
            if after.git_metadata_manifest != before.git_metadata_manifest:
                raise WorkerViolation("worker modified protected git metadata")
            if task.kind is WorkerKind.ANALYSIS and (
                delta_paths or after.submodule_status != before.submodule_status
            ):
                raise WorkerViolation("analysis worker modified the approved worktree")
            if self.backend is not None:
                unexpected = tuple(
                    path
                    for path in delta_paths
                    if path not in exported_paths
                    and not any(
                        exported.startswith(path.rstrip("/") + "/")
                        for exported in exported_paths
                    )
                )
                if unexpected:
                    raise WorkerViolation("host delta disagrees with guest export")
                delta_paths = exported_paths
            return _GitSnapshot(
                after.diff,
                after.name_status,
                delta_paths,
                after.worktree_manifest,
                after.git_metadata_manifest,
                after.submodule_status,
            )

        def validate_result(
            completed: subprocess.CompletedProcess[str],
        ) -> _GitSnapshot:
            del completed
            return validated_snapshot(())

        def prepare_result(
            completed: subprocess.CompletedProcess[str],
        ) -> tuple[str, object]:
            if self.backend is None:
                raise WorkerViolation("isolated backend is unavailable")
            intermediate = self._snapshot(root)
            if (
                self._delta_paths(before, intermediate)
                or intermediate.git_metadata_manifest != before.git_metadata_manifest
                or intermediate.submodule_status != before.submodule_status
            ):
                raise WorkerViolation(
                    "host worktree changed while isolated worker was running"
                )
            return self.backend.prepare_export(
                task,
                completed.stdout or "",
                grant.effect_id,
                grant.fence,
            )

        def commit_result(
            prepared: object,
            authority_check: Callable[[], None],
        ) -> _GitSnapshot:
            if self.backend is None:
                raise WorkerViolation("isolated backend is unavailable")
            exported_paths = self.backend.commit_export(
                task,
                prepared,
                authority_check,
            )
            return validated_snapshot(exported_paths)

        if self.backend is not None:
            request_record: dict[str, object] = {
                "schema_version": "1.0",
                "approved_context": task.approved_context,
                "allowed_paths": list(task.allowed_paths),
                "effect_id": grant.effect_id,
                "fence": grant.fence,
                "task_fingerprint": task.fingerprint(),
            }
            request_record.update(self.backend.request_payload(task))
            stdin_text = json.dumps(
                request_record,
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            stdin_text = task.approved_context
        effect, validated = self.broker._dispatch(
            grant,
            command,
            stdin_text=stdin_text,
            result_validator=validate_result if self.backend is None else None,
            result_preparer=prepare_result if self.backend is not None else None,
            result_committer=commit_result if self.backend is not None else None,
            sandbox_read_roots=()
            if self.backend is not None
            else (
                self._git(
                    root, "rev-parse", "--path-format=absolute", "--git-dir"
                ).strip(),
                self._git(
                    root,
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                ).strip(),
            ),
        )
        if (
            self.backend is not None
            and effect.status is DispatchStatus.RECONCILIATION_REQUIRED
        ):
            self.backend.cancel(
                task,
                grant.effect_id,
                task.fingerprint(),
                grant.fence,
            )
        after = (
            validated if isinstance(validated, _GitSnapshot) else self._snapshot(root)
        )
        return WorkerResult(
            effect,
            before.diff,
            before.name_status,
            after.diff,
            after.name_status,
            after.changed_paths,
        )

    def adopt_prepared(
        self,
        task: WorkerTask,
        grant: Grant,
        prior_stage_ref: str,
        prepared: object,
    ) -> WorkerResult:
        """Commit a reconciled durable stage under a newly authorized fence."""
        if self.backend is None:
            raise WorkerViolation("prepared adoption requires an isolated backend")
        root = self._validate_root(task, grant)
        self.build_command(task, grant)
        before = self._snapshot(root)
        adopted = self.backend.adopt_export(prepared, grant.fence)
        adopted_ref = getattr(adopted, "stage_ref", None)
        if not isinstance(adopted_ref, str):
            raise WorkerViolation("adopted stage has no durable evidence")

        def commit(
            value: object, authority_check: Callable[[], None]
        ) -> tuple[str, ...]:
            return self.backend.commit_export(task, value, authority_check)

        effect, exported = self.broker.commit_prepared_adoption(
            grant,
            prior_stage_ref,
            adopted_ref,
            adopted,
            commit,
        )
        after = self._snapshot(root)
        delta_paths = self._delta_paths(before, after)
        self._validate_changed_paths(root, delta_paths)
        if after.git_metadata_manifest != before.git_metadata_manifest:
            raise WorkerViolation("prepared adoption modified protected git metadata")
        exported_paths = exported if isinstance(exported, tuple) else ()
        if effect.status is DispatchStatus.COMPLETED and delta_paths != tuple(
            sorted(exported_paths)
        ):
            raise WorkerViolation("prepared adoption delta disagrees with its stage")
        return WorkerResult(
            effect,
            before.diff,
            before.name_status,
            after.diff,
            after.name_status,
            delta_paths,
        )
