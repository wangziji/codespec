from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from codex_contract_delivery.capabilities import (
    CapabilityBroker,
    CapabilityPolicy,
    CapabilityRequest,
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
    grant = broker.authorize(
        CapabilityRequest("controller", capability, str(root), operation), context
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
        tmp_path, root, capability="worker.analysis", operation="read", runner=runner
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
