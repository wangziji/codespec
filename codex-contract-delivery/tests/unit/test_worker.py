from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from codex_contract_delivery.capabilities import (
    CapabilityBroker,
    CapabilityPolicy,
    CapabilityRequest,
    DispatchStatus,
    RunContext,
)
from codex_contract_delivery.journal import EffectIntent, Journal, TransitionRequest
from codex_contract_delivery.state_machine import RunEvent, RunState
from codex_contract_delivery.worker import (
    WorkerKind,
    WorkerLauncher,
    WorkerTask,
    WorkerViolation,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex"


def initialize_primary_git(root: Path) -> None:
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(
        ("git", "-C", str(root), "config", "user.email", "test@example.invalid"),
        check=True,
    )
    subprocess.run(("git", "-C", str(root), "config", "user.name", "Test"), check=True)
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(root), "add", "tracked.txt"), check=True)
    subprocess.run(("git", "-C", str(root), "commit", "-qm", "base"), check=True)


def initialize_git(root: Path) -> None:
    if root.exists():
        root.rmdir()
    source = root.parent / f"{root.name}-source"
    source.mkdir()
    initialize_primary_git(source)
    subprocess.run(
        (
            "git",
            "-C",
            str(source),
            "worktree",
            "add",
            "--detach",
            "-q",
            str(root),
            "HEAD",
        ),
        check=True,
    )


def authorized(
    tmp_path: Path,
    root: Path,
    *,
    capability: str,
    operation: str,
    runner: object,
    approved_context: str = "write",
) -> tuple[CapabilityBroker, object, Journal]:
    journal = Journal.open(tmp_path / f"{capability.replace('.', '-')}.sqlite3")
    result = journal.transition(
        TransitionRequest(
            "run-1",
            0,
            RunEvent.DISCOVER,
            {},
            EffectIntent(f"effect-{capability}", "worker"),
        )
    )
    policy = CapabilityPolicy.from_mapping(
        {
            "schema_version": "1.0",
            "workflow_release_digest": DIGEST_B,
            "policies": [
                {
                    "policy_id": "worker-v1",
                    "capability": capability,
                    "operation": operation,
                    "resource_pattern": str(root),
                    "allowed_argv_prefix": [CODEX, "exec"],
                    "required_run_state": "discovery",
                    "approval_digest": DIGEST_A,
                    "actor_class": "controller",
                    "timeout_seconds": 30,
                    "idempotency_strategy": "effect-id",
                    "reconciliation_strategy": "journal-probe",
                    "allowed_environment_names": ["HOME", "PATH", "CODEX_HOME"],
                    "allowed_write_roots": [str(root)] if operation == "write" else [],
                }
            ],
        }
    )
    broker = CapabilityBroker(policy, journal, process_runner=runner)
    context = RunContext(
        run_id="run-1",
        revision=result.run.revision,
        state=RunState.DISCOVERY,
        workflow_release_digest=DIGEST_B,
        approval_digest=DIGEST_A,
        actor_class="controller",
        effect_id=f"effect-{capability}",
        worker_id="controller-1",
    )
    kind = (
        WorkerKind.ANALYSIS
        if capability == "worker.analysis"
        else WorkerKind.IMPLEMENTATION
    )
    task = WorkerTask(kind, root, approved_context)
    command = WorkerLauncher.canonical_command(task, CODEX)
    grant = broker.authorize(
        CapabilityRequest(
            "controller",
            capability,
            str(root),
            operation,
            command,
            task.fingerprint(),
        ),
        context,
    )
    return broker, grant, journal


def test_worker_commands_are_ephemeral_sandboxed_and_receive_context_on_stdin(
    tmp_path: Path,
) -> None:
    """Would fail if workers loaded ambient rules/config or received prompt shell text."""
    root = tmp_path / "worktree"
    root.mkdir()
    initialize_git(root)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"type":"done"}\n', stderr=""
        )

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
        approved_context="controller approved context",
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)
    task = WorkerTask(WorkerKind.IMPLEMENTATION, root, "controller approved context")

    command = launcher.build_command(task, grant)
    result = launcher.run(task, grant)

    assert command == (
        CODEX,
        "exec",
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(root.resolve()),
        "--json",
        "-",
    )
    assert calls[0][1]["input"] == "controller approved context"
    assert "controller approved context" not in calls[0][0]
    assert result.changed_paths == ()
    journal.close()


def test_isolated_worker_commits_with_host_authority_check_only(
    tmp_path: Path,
) -> None:
    """Would fail if durable host authority leaked into the guest export protocol."""
    root = tmp_path / "worktree"
    root.mkdir()
    initialize_git(root)
    request_records: list[dict[str, object]] = []
    authority_checks: list[object] = []

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        request_records.append(json.loads(str(kwargs["input"])))
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    task = WorkerTask(WorkerKind.IMPLEMENTATION, root, "write")

    class Backend:
        def canonical_command(self, current: WorkerTask) -> tuple[str, ...]:
            return WorkerLauncher.canonical_command(current, CODEX)

        def request_payload(self, current: WorkerTask) -> dict[str, str]:
            return {}

        def prepare_export(
            self,
            current: WorkerTask,
            stdout: str,
            effect_id: str,
            fence: int,
        ) -> tuple[str, object]:
            return ("effect-stage://sha256/" + "a" * 64, object())

        def commit_export(
            self,
            current: WorkerTask,
            prepared: object,
            authority_check: object,
        ) -> tuple[str, ...]:
            authority_checks.append(authority_check)
            assert callable(authority_check)
            authority_check(1.0)
            return ()

        def adopt_export(self, prepared: object, fence: int) -> object:
            raise AssertionError("run must not adopt an export")

        def cancel(
            self,
            current: WorkerTask,
            effect_id: str,
            task_fingerprint: str,
            fence: int,
        ) -> None:
            raise AssertionError("successful run must not cancel the export")

    result = WorkerLauncher(broker, backend=Backend()).run(task, grant)

    assert result.effect.status is DispatchStatus.COMPLETED
    assert len(authority_checks) == 1
    assert set(request_records[0]) == {
        "schema_version",
        "approved_context",
        "allowed_paths",
        "effect_id",
        "fence",
        "task_fingerprint",
    }
    journal.close()


def test_analysis_worker_is_read_only_and_rejects_any_tree_change(
    tmp_path: Path,
) -> None:
    """Would fail if an analysis worker could return successfully after writing."""
    root = tmp_path / "analysis"
    root.mkdir()
    initialize_git(root)

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        (root / "forbidden.txt").write_text("write\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.analysis",
        operation="read",
        runner=runner,
        approved_context="inspect only",
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)
    task = WorkerTask(WorkerKind.ANALYSIS, root, "inspect only")

    assert launcher.build_command(task, grant)[3] == "read-only"
    with pytest.raises(WorkerViolation, match="analysis worker modified"):
        launcher.run(task, grant)
    journal.close()


def test_implementation_worker_returns_real_git_name_status_diff(
    tmp_path: Path,
) -> None:
    """Would fail if worker writes were not measured from the approved git worktree."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (root / "new.txt").write_text("new\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
        approved_context="make approved change",
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    result = launcher.run(
        WorkerTask(WorkerKind.IMPLEMENTATION, root, "make approved change"), grant
    )

    assert result.changed_paths == ("new.txt", "tracked.txt")
    assert "tracked.txt" in result.after_name_status
    assert "changed" in result.after_diff
    journal.close()


@pytest.mark.parametrize(
    "capability",
    ["github.write", "penpot.write", "deploy", "secret.read", "prod.release"],
)
def test_workers_never_receive_broker_owned_capabilities(
    tmp_path: Path, capability: str
) -> None:
    """Would fail if a generic worker grant could carry a protected adapter capability."""
    root = tmp_path / "worktree"
    root.mkdir(exist_ok=True)
    initialize_git(root)
    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability=capability,
        operation="read",
        runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    with pytest.raises(WorkerViolation, match="broker-owned"):
        launcher.build_command(WorkerTask(WorkerKind.ANALYSIS, root, "inspect"), grant)
    journal.close()


def test_worker_rejects_symlinked_or_non_git_root_before_execution(
    tmp_path: Path,
) -> None:
    """Would fail if --cd could be redirected outside the approved real worktree."""
    root = tmp_path / "real"
    root.mkdir()
    initialize_git(root)
    link = tmp_path / "linked"
    link.symlink_to(root, target_is_directory=True)
    calls = 0

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, "", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    with pytest.raises(WorkerViolation, match="symlink"):
        launcher.run(WorkerTask(WorkerKind.IMPLEMENTATION, link, "write"), grant)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorkerViolation, match="git worktree"):
        launcher.run(WorkerTask(WorkerKind.IMPLEMENTATION, plain, "write"), grant)
    assert calls == 0
    journal.close()


def test_worker_rejects_changed_symlink_and_path_escape(tmp_path: Path) -> None:
    """Would fail if a worker could hide an out-of-scope target behind a new symlink."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        (root / "escape").symlink_to(outside)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    with pytest.raises(WorkerViolation, match="symlink"):
        launcher.run(WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant)
    journal.close()


def test_implementation_worker_requires_linked_worktree_before_execution(
    tmp_path: Path,
) -> None:
    """Would fail if an implementation worker could mutate a primary checkout."""
    root = tmp_path / "primary"
    root.mkdir()
    initialize_primary_git(root)
    calls = 0

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, "", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    with pytest.raises(WorkerViolation, match="linked git worktree"):
        launcher.run(WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant)
    assert calls == 0
    journal.close()


def test_worker_rejects_preexisting_symlink_before_execution(tmp_path: Path) -> None:
    """Would fail if an unchanged symlink could redirect writes outside the worktree."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (root / "existing-link").symlink_to(outside)
    calls = 0

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, "", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    launcher = WorkerLauncher(broker, codex_executable=CODEX)

    with pytest.raises(WorkerViolation, match="symlink"):
        launcher.run(WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant)
    assert calls == 0
    journal.close()


@pytest.mark.parametrize(
    "extra",
    [
        ("--dangerously-bypass-approvals-and-sandbox",),
        ("--approve-for-me",),
        ("--add-dir", "/tmp"),
        ("--sandbox", "danger-full-access"),
        ("--sandbox", "workspace-write", "--sandbox", "read-only"),
        ("untrusted prompt text",),
    ],
)
def test_direct_dispatch_cannot_extend_a_legal_worker_grant(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    """Would fail if a legal worker prefix could authorize attacker-chosen flags."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    calls = 0

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, "", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )

    with pytest.raises(Exception, match="argv|worker command|danger|grant"):
        broker.dispatch(grant, (CODEX, "exec", *extra))
    assert calls == 0
    journal.close()


def test_worker_delta_includes_ignored_binary_mode_rename_delete_but_not_unchanged_dirty(
    tmp_path: Path,
) -> None:
    """Would fail if the snapshot were only the current non-ignored git status."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    source = root.parent / "implementation-source"
    (source / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
    (source / "delete.txt").write_text("delete\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(source), "add", ".gitignore", "delete.txt"), check=True
    )
    subprocess.run(("git", "-C", str(source), "commit", "-qm", "fixtures"), check=True)
    revision = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(("git", "-C", str(root), "reset", "--hard", revision), check=True)
    (root / "tracked.txt").write_text("preexisting dirty\n", encoding="utf-8")
    (root / "ignored.bin").write_bytes(b"before\x00")

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        (root / "ignored.bin").write_bytes(b"after\x00")
        (root / "delete.txt").unlink()
        (root / ".gitignore").rename(root / "renamed-ignore")
        (root / "binary.dat").write_bytes(b"\x00\xff\x01")
        (root / "binary.dat").chmod(0o700)
        return subprocess.CompletedProcess(argv, 0, "done", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    result = WorkerLauncher(broker, codex_executable=CODEX).run(
        WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant
    )

    assert result.changed_paths == (
        ".gitignore",
        "binary.dat",
        "delete.txt",
        "ignored.bin",
        "renamed-ignore",
    )
    assert "tracked.txt" not in result.changed_paths
    journal.close()


def test_worker_rejects_git_common_metadata_delta(tmp_path: Path) -> None:
    """Would fail if a worker could alter hooks or worktree refs outside the root."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    common = Path(
        subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        hook = common / "hooks" / "post-checkout"
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "done", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )

    with pytest.raises(WorkerViolation, match="git metadata"):
        WorkerLauncher(broker, codex_executable=CODEX).run(
            WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant
        )
    journal.close()


def test_worker_delta_observes_nested_submodule_change(tmp_path: Path) -> None:
    """Would fail if nested submodule worktrees were absent from the delta."""
    nested = tmp_path / "nested-source"
    nested.mkdir()
    initialize_primary_git(nested)
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)
    source = root.parent / "implementation-source"
    subprocess.run(
        (
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(source),
            "submodule",
            "add",
            "-q",
            str(nested),
            "sub",
        ),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(source), "commit", "-qam", "submodule"), check=True
    )
    revision = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(("git", "-C", str(root), "reset", "--hard", revision), check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(root),
            "submodule",
            "update",
            "--init",
            "-q",
        ),
        check=True,
    )

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        (root / "sub" / "tracked.txt").write_text("nested delta\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "done", "")

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=runner,
    )
    result = WorkerLauncher(broker, codex_executable=CODEX).run(
        WorkerTask(WorkerKind.IMPLEMENTATION, root, "write"), grant
    )

    assert "sub/tracked.txt" in result.changed_paths
    journal.close()


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        (
            (
                '{"item":{"type":"command_execution","status":"failed",'
                '"exit_code":1,"aggregated_output":"Operation not permitted"}}\n'
            ),
            0,
            DispatchStatus.DENIED,
        ),
        (
            '{"type":"item.completed","item":{"type":"agent_message"}}\n',
            0,
            DispatchStatus.COMPLETED,
        ),
        ("", 2, DispatchStatus.FAILED),
    ],
)
def test_worker_result_distinguishes_sandbox_denial_model_refusal_and_failure(
    tmp_path: Path,
    stdout: str,
    returncode: int,
    expected: DispatchStatus,
) -> None:
    """Would fail if every Codex process exit were recorded as completed."""
    root = tmp_path / "analysis"
    root.mkdir()
    initialize_git(root)
    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.analysis",
        operation="read",
        approved_context="inspect only",
        runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, ""
        ),
    )

    result = WorkerLauncher(broker, codex_executable=CODEX).run(
        WorkerTask(WorkerKind.ANALYSIS, root, "inspect only"), grant
    )

    assert result.effect.status is expected
    journal.close()


def test_remote_backend_cancels_guest_task_after_host_timeout(tmp_path: Path) -> None:
    """Would fail if killing limactl left a remote task alive past its fence."""
    root = tmp_path / "implementation"
    root.mkdir()
    initialize_git(root)

    def timeout(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    broker, grant, journal = authorized(
        tmp_path,
        root,
        capability="worker.implementation",
        operation="write",
        runner=timeout,
    )
    task = WorkerTask(WorkerKind.IMPLEMENTATION, root, "write")

    class Backend:
        def __init__(self) -> None:
            self.cancelled: tuple[str, str, int] | None = None

        def canonical_command(self, current: WorkerTask) -> tuple[str, ...]:
            return WorkerLauncher.canonical_command(current, CODEX)

        def request_payload(self, current: WorkerTask) -> dict[str, str]:
            return {}

        def prepare_export(
            self,
            current: WorkerTask,
            stdout: str,
            effect_id: str,
            fence: int,
        ) -> tuple[str, object]:
            raise AssertionError("timeout must never import an export")

        def commit_export(
            self,
            current: WorkerTask,
            prepared: object,
            authority_check: object,
        ) -> tuple[str, ...]:
            raise AssertionError("timeout must never commit an export")

        def cancel(
            self,
            current: WorkerTask,
            effect_id: str,
            task_fingerprint: str,
            fence: int,
        ) -> None:
            self.cancelled = (effect_id, task_fingerprint, fence)

    backend = Backend()
    result = WorkerLauncher(broker, backend=backend).run(task, grant)

    assert result.effect.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert backend.cancelled == (grant.effect_id, task.fingerprint(), grant.fence)
    journal.close()
