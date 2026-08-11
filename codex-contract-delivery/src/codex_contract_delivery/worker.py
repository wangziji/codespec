"""Codex worker command construction and git-bound write verification."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .capabilities import CapabilityBroker, EffectResult, Grant


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


@dataclass(frozen=True)
class _GitSnapshot:
    diff: str
    name_status: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class WorkerResult:
    effect: EffectResult
    before_diff: str
    before_name_status: str
    after_diff: str
    after_name_status: str
    changed_paths: tuple[str, ...]


_BROKER_OWNED = ("github", "penpot", "deploy", "secret", "prod")


class WorkerLauncher:
    """Launch only controller-scoped Codex workers in an approved real git root."""

    def __init__(self, broker: CapabilityBroker, *, codex_executable: str) -> None:
        self.broker = broker
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
            root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
        return _GitSnapshot(diff, status, self._parse_status(status))

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
        root = self._validate_root(task, grant)
        command = (
            self.codex_executable,
            "exec",
            "--sandbox",
            "read-only" if task.kind is WorkerKind.ANALYSIS else "workspace-write",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--cd",
            str(root),
            "--json",
            "-",
        )
        if command[: len(grant.allowed_argv_prefix)] != grant.allowed_argv_prefix:
            raise WorkerViolation(
                "worker command does not match the granted argv prefix"
            )
        return command

    def run(self, task: WorkerTask, grant: Grant) -> WorkerResult:
        root = self._validate_root(task, grant)
        command = self.build_command(task, grant)
        before = self._snapshot(root)

        def validate_result(
            completed: subprocess.CompletedProcess[str],
        ) -> _GitSnapshot:
            del completed
            after = self._snapshot(root)
            self._validate_changed_paths(root, after.changed_paths)
            if task.kind is WorkerKind.ANALYSIS and after != before:
                raise WorkerViolation("analysis worker modified the approved worktree")
            return after

        effect, validated = self.broker._dispatch(
            grant,
            command,
            stdin_text=task.approved_context,
            result_validator=validate_result,
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
