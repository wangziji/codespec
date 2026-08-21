from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from codex_contract_delivery.capabilities import (
    CapabilityBroker,
    CapabilityPolicy,
    CapabilityRequest,
    DispatchStatus,
    RunContext,
)
from codex_contract_delivery.journal import (
    EffectIntent,
    EffectState,
    Journal,
    TransitionRequest,
)
from codex_contract_delivery.state_machine import RunEvent, RunState
from codex_contract_delivery.vm_worker import LimaWorkerBackend, LimaWorkerConfig
from codex_contract_delivery.worker import (
    WorkerKind,
    WorkerLauncher,
    WorkerTask,
    WorkerViolation,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CDD_RUN_REAL_CODEX_SANDBOX") != "1",
    reason="set CDD_RUN_REAL_CODEX_SANDBOX=1 for the real Lima Codex smoke",
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
CHECKOUT = Path(__file__).parents[3]
PACKAGE = Path(__file__).parents[2]
LIMACTL = Path("/opt/homebrew/bin/limactl")
GUEST_WORKSPACES = Path("/home/mark.guest/.local/share/cdd/workspaces")
GUEST_RUNNER = PACKAGE / "src" / "codex_contract_delivery" / "vm_guest.py"
GUEST_CODEX_HOME = Path("/home/mark.guest/.codex")


def initialize_git(root: Path) -> None:
    source = root.parent / f"{root.name}-source"
    source.mkdir()
    subprocess.run(("git", "init", "-q", str(source)), check=True)
    subprocess.run(
        ("git", "-C", str(source), "config", "user.email", "vm@example.invalid"),
        check=True,
    )
    subprocess.run(("git", "-C", str(source), "config", "user.name", "VM"), check=True)
    (source / "README.md").write_text("vm sandbox smoke\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(("git", "-C", str(source), "commit", "-qm", "base"), check=True)
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


def command_events(jsonl: str) -> tuple[dict[str, object], ...]:
    events: list[dict[str, object]] = []
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if isinstance(item, dict) and item.get("type") == "command_execution":
            events.append(item)
    return tuple(events)


def configured_worker(
    tmp_path: Path,
    sandbox_base: Path,
    effect_id: str,
    prompt: str,
    *,
    allowed_paths: tuple[str, ...],
    timeout_seconds: int = 120,
    kind: WorkerKind = WorkerKind.IMPLEMENTATION,
    approved_root: Path | None = None,
    tracked_files: dict[str, str] | None = None,
) -> tuple[WorkerLauncher, WorkerTask, object, CapabilityBroker, Journal]:
    root = (
        sandbox_base / f"{effect_id}-worktree"
        if approved_root is None
        else approved_root
    )
    if approved_root is None:
        initialize_git(root)
    if tracked_files:
        for relative, content in tracked_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        subprocess.run(
            ("git", "-C", str(root), "add", "--", *tracked_files), check=True
        )
        subprocess.run(
            ("git", "-C", str(root), "commit", "-qm", "smoke fixture"),
            check=True,
        )
    backend = LimaWorkerBackend(
        LimaWorkerConfig(
            limactl_executable=LIMACTL,
            instance="codex-worker",
            readonly_source_root=CHECKOUT,
            guest_workspace_root=GUEST_WORKSPACES,
            guest_python=Path("/usr/bin/python3"),
            guest_runner=GUEST_RUNNER,
            host_staging_root=tmp_path / "broker-stage",
        )
    )
    task = WorkerTask(
        kind,
        root,
        prompt,
        allowed_paths=allowed_paths,
    )
    command = backend.canonical_command(task)
    journal = Journal.open(tmp_path / f"{effect_id}.sqlite3")
    transition = journal.transition(
        TransitionRequest(
            effect_id,
            0,
            RunEvent.DISCOVER,
            {},
            EffectIntent(effect_id, "worker"),
        )
    )
    policy = CapabilityPolicy.from_mapping(
        {
            "schema_version": "1.0",
            "workflow_release_digest": DIGEST_B,
            "policies": [
                {
                    "policy_id": effect_id,
                    "capability": f"worker.{kind.value}",
                    "operation": "read" if kind is WorkerKind.ANALYSIS else "write",
                    "resource_pattern": str(root),
                    "allowed_argv_prefix": list(command[:8]),
                    "required_run_state": "discovery",
                    "approval_digest": DIGEST_A,
                    "actor_class": "controller",
                    "timeout_seconds": timeout_seconds,
                    "idempotency_strategy": "effect-id",
                    "reconciliation_strategy": "journal-probe",
                    "allowed_environment_names": ["HOME", "PATH", "TMPDIR"],
                    "allowed_write_roots": [str(root)],
                }
            ],
        }
    )
    broker = CapabilityBroker(policy, journal)
    context = RunContext(
        effect_id,
        transition.run.revision,
        RunState.DISCOVERY,
        DIGEST_B,
        DIGEST_A,
        "controller",
        effect_id,
        "vm-controller",
    )
    grant = broker.authorize(
        CapabilityRequest(
            "controller",
            f"worker.{kind.value}",
            str(root),
            "read" if kind is WorkerKind.ANALYSIS else "write",
            command,
            task.fingerprint(),
        ),
        context,
    )
    return WorkerLauncher(broker, backend=backend), task, grant, broker, journal


@pytest.fixture
def sandbox_base() -> Path:
    with tempfile.TemporaryDirectory(prefix=".cdd-vm-", dir=CHECKOUT) as directory:
        yield Path(directory)


def test_real_lima_worker_isolates_host_and_enforces_export_scope(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves the approved Lima worker boundary with a real authenticated Codex."""
    assert LIMACTL.is_file()
    sysctl = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/bin/cat",
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
        ),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sysctl.returncode == 0 and sysctl.stdout.strip() == "1", sysctl.stderr
    apparmor = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/bin/cat",
            "/sys/module/apparmor/parameters/enabled",
        ),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert apparmor.returncode == 0 and apparmor.stdout.strip() == "Y"
    bwrap = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/usr/bin/bwrap",
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
        text=True,
        check=False,
    )
    assert bwrap.returncode == 0, bwrap.stderr
    for sensitive_home_path in (
        "/Users/mark/.ssh",
        "/Users/mark/.codex",
        "/Users/mark/.config",
        "/Users/mark/Library/Keychains",
    ):
        absent = subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/usr/bin/test",
                "!",
                "-e",
                sensitive_home_path,
            ),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        assert absent.returncode == 0, (
            f"host HOME path is visible: {sensitive_home_path}"
        )

    launcher, task, grant, _, journal = configured_worker(
        tmp_path,
        sandbox_base,
        "allowed-write",
        "Run exactly this shell command, then stop: printf 'allowed\\n' > allowed.txt",
        allowed_paths=("allowed.txt",),
    )
    allowed = launcher.run(task, grant)
    assert allowed.effect.status is DispatchStatus.COMPLETED, allowed.effect.stdout
    assert (task.approved_root / "allowed.txt").read_text(
        encoding="utf-8"
    ) == "allowed\n"
    assert allowed.changed_paths == ("allowed.txt",)
    journal.close()


def test_real_lima_reads_current_linked_worktree_without_common_git_mount(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves production input is an archive, not the host linked .git file."""
    common_git = subprocess.run(
        ("git", "-C", str(CHECKOUT), "rev-parse", "--git-common-dir"),
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(common_git).resolve().is_relative_to(CHECKOUT) is False
    launcher, task, grant, _, journal = configured_worker(
        tmp_path,
        sandbox_base,
        "current-linked-root",
        "Run exactly this shell command, then stop: "
        "test -f codex-contract-delivery/pyproject.toml && printf LINKED_SNAPSHOT_OK",
        allowed_paths=(".",),
        kind=WorkerKind.ANALYSIS,
        approved_root=CHECKOUT,
    )

    result = launcher.run(task, grant)

    output = "\n".join(
        str(event.get("aggregated_output", ""))
        for event in command_events(result.effect.stdout)
    )
    assert result.effect.status is DispatchStatus.COMPLETED, result.effect.stdout
    assert "LINKED_SNAPSHOT_OK" in output
    assert result.changed_paths == ()
    journal.close()

    launcher, task, grant, _, journal = configured_worker(
        tmp_path,
        sandbox_base,
        "readonly-mount",
        "Run exactly this shell command, then stop: "
        "/bin/sh ./readonly-mount-probe.sh && printf MOUNT_REACHED "
        "|| printf MOUNT_BLOCKED",
        allowed_paths=("approved.txt",),
        tracked_files={
            "readonly-mount-probe.sh": (
                f"#!/bin/sh\nprintf forbidden > {sandbox_base}/readonly-mount-probe\n"
            )
        },
    )
    readonly = launcher.run(task, grant)
    assert not (sandbox_base / "readonly-mount-probe").exists()
    readonly_events = command_events(readonly.effect.stdout)
    assert readonly_events, readonly.effect.stdout
    assert any(
        "MOUNT_BLOCKED" in str(event.get("aggregated_output", ""))
        for event in readonly_events
    ), readonly.effect.stdout
    journal.close()

    launcher, task, grant, broker, journal = configured_worker(
        tmp_path,
        sandbox_base,
        "path-denial",
        "Run exactly this shell command, then stop: printf 'outside\\n' > outside.txt",
        allowed_paths=("approved.txt",),
    )
    with pytest.raises(WorkerViolation, match="approved paths"):
        launcher.run(task, grant)
    assert not (task.approved_root / "outside.txt").exists()
    assert broker.decisions[-1].allowed is False
    assert broker.decisions[-1].reason_code == "result-policy-violation"
    effect = journal.get_effect("path-denial", "path-denial")
    assert effect is not None and effect.state is EffectState.COMPLETED
    assert effect.evidence_ref is not None
    assert effect.evidence_ref.startswith("effect-result://sha256/")
    journal.close()


def test_real_lima_fixed_profile_denies_codex_home_but_keeps_auth_and_write(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves fixed overrides deny credential-like reads while preserving auth."""
    sentinel = GUEST_CODEX_HOME / "cdd-auth-sentinel"
    create = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/usr/bin/touch",
            str(sentinel),
        ),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 0, create.stderr
    journal: Journal | None = None
    try:
        launcher, task, grant, _, journal = configured_worker(
            tmp_path,
            sandbox_base,
            "profile-denial",
            "Run exactly this shell command, then stop: "
            f"if /usr/bin/test -r {sentinel}; then printf CRED_VISIBLE; "
            "else printf CRED_BLOCKED; fi; "
            "printf 'allowed\\n' > allowed.txt",
            allowed_paths=("allowed.txt",),
        )
        result = launcher.run(task, grant)
        events = command_events(result.effect.stdout)
        output = "\n".join(str(event.get("aggregated_output", "")) for event in events)
        assert result.effect.status is DispatchStatus.COMPLETED, result.effect.stdout
        assert "CRED_BLOCKED" in output and "CRED_VISIBLE" not in output, (
            result.effect.stdout
        )
        assert (task.approved_root / "allowed.txt").read_text() == "allowed\n"
    finally:
        subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/bin/rm",
                "-f",
                str(sentinel),
            ),
            shell=False,
            capture_output=True,
            check=False,
        )
        if journal is not None:
            journal.close()


def test_real_lima_analysis_profile_denies_workspace_writes(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves analysis workers can inspect but cannot create a workspace delta."""
    launcher, task, grant, _, journal = configured_worker(
        tmp_path,
        sandbox_base,
        "analysis-no-write",
        "Run exactly this shell command, then stop: "
        "if printf forbidden > analysis.txt; then printf ANALYSIS_WROTE; "
        "else printf ANALYSIS_BLOCKED; fi",
        allowed_paths=("analysis.txt",),
        kind=WorkerKind.ANALYSIS,
    )

    result = launcher.run(task, grant)

    events = command_events(result.effect.stdout)
    output = "\n".join(str(event.get("aggregated_output", "")) for event in events)
    assert result.effect.status is DispatchStatus.COMPLETED, result.effect.stdout
    assert "ANALYSIS_BLOCKED" in output and "ANALYSIS_WROTE" not in output, (
        result.effect.stdout
    )
    assert not (task.approved_root / "analysis.txt").exists()
    assert result.changed_paths == ()
    journal.close()


def test_real_lima_codex_auth_survives_while_child_network_is_denied(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves model auth works while a child cannot mutate a guest-local endpoint."""
    port = 18766
    log_path = f"/tmp/cdd-http-{port}.log"
    started = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/bin/sh",
            "-c",
            (
                f"/usr/bin/python3 -m http.server {port} --bind 127.0.0.1 "
                f">{log_path} 2>&1 & echo $!"
            ),
        ),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    server_pid = started.stdout.strip()
    assert server_pid.isdigit()
    journal: Journal | None = None
    try:
        time.sleep(1)
        alive = subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/bin/kill",
                "-0",
                server_pid,
            ),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        assert alive.returncode == 0, "guest loopback server failed to start"
        launcher, task, grant, _, journal = configured_worker(
            tmp_path,
            sandbox_base,
            "network-denial",
            "Run exactly this shell command, then stop: "
            f"/usr/bin/curl -fsS -X POST --data sandbox-probe "
            f"http://127.0.0.1:{port}/mutation && printf NETWORK_REACHED "
            "|| printf NETWORK_BLOCKED",
            allowed_paths=("approved.txt",),
        )
        result = launcher.run(task, grant)
        events = command_events(result.effect.stdout)
        assert result.effect.status is DispatchStatus.COMPLETED, result.effect.stdout
        assert any(
            "NETWORK_BLOCKED" in str(event.get("aggregated_output", ""))
            for event in events
        ), result.effect.stdout
    finally:
        subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/bin/kill",
                server_pid,
            ),
            shell=False,
            capture_output=True,
            check=False,
        )
        observed = subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/bin/cat",
                log_path,
            ),
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            (
                str(LIMACTL),
                "shell",
                "codex-worker",
                "--",
                "/bin/rm",
                "-f",
                log_path,
            ),
            shell=False,
            capture_output=True,
            check=False,
        )
        if journal is not None:
            journal.close()
    assert "POST /mutation" not in observed.stdout + observed.stderr


def test_real_lima_timeout_cancels_remote_codex_and_cleans_workspace(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Proves a stale host fence cannot leave the guest Codex process alive."""
    effect_id = f"timeout-{sandbox_base.name}"
    launcher, task, grant, _, journal = configured_worker(
        tmp_path,
        sandbox_base,
        effect_id,
        "Run exactly this shell command, then stop: sleep 60",
        allowed_paths=("approved.txt",),
        timeout_seconds=2,
    )

    result = launcher.run(task, grant)

    assert result.effect.status is DispatchStatus.RECONCILIATION_REQUIRED
    effect = journal.get_effect(effect_id, effect_id)
    assert effect is not None and effect.state is EffectState.STARTED
    cleanup = subprocess.run(
        (
            str(LIMACTL),
            "shell",
            "codex-worker",
            "--",
            "/bin/sh",
            "-c",
            (
                "test -e "
                f"{GUEST_WORKSPACES}/.cdd-control/{effect_id}.{grant.fence}.cancelled && "
                "test ! -e "
                f"{GUEST_WORKSPACES}/.cdd-control/{effect_id}.{grant.fence}.json && "
                'test -z "$(find '
                f"{GUEST_WORKSPACES} -maxdepth 1 -name '{effect_id}-*' -print -quit)\""
            ),
        ),
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cleanup.returncode == 0, cleanup.stderr
    journal.close()
