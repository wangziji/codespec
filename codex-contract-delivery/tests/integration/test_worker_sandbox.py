from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from codex_contract_delivery.worker import WorkerKind, WorkerLauncher, WorkerTask

pytestmark = pytest.mark.skipif(
    os.environ.get("CDD_RUN_REAL_CODEX_SANDBOX") != "1",
    reason="set CDD_RUN_REAL_CODEX_SANDBOX=1 for the real local Codex sandbox smoke",
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")


def initialize_git(root: Path) -> None:
    root.rmdir()
    source = root.parent / "source"
    source.mkdir()
    subprocess.run(("git", "init", "-q", str(source)), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(source),
            "config",
            "user.email",
            "sandbox@example.invalid",
        ),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(source), "config", "user.name", "Sandbox Smoke"),
        check=True,
    )
    (source / "README.md").write_text("sandbox smoke\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("git", "-C", str(source), "commit", "-qm", "sandbox base"), check=True
    )
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


def run_worker(tmp_path: Path, root: Path, effect_id: str, prompt: str):
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
            "policies": [
                {
                    "policy_id": effect_id,
                    "capability": "worker.implementation",
                    "operation": "write",
                    "resource_pattern": str(root),
                    "allowed_argv_prefix": [str(CODEX), "exec"],
                    "required_run_state": "discovery",
                    "approval_digest": DIGEST_A,
                    "actor_class": "controller",
                    "timeout_seconds": 120,
                    "idempotency_strategy": "effect-id",
                    "reconciliation_strategy": "journal-probe",
                    "allowed_environment_names": [
                        "HOME",
                        "PATH",
                        "LANG",
                        "LC_ALL",
                        "TMPDIR",
                        "CODEX_HOME",
                    ],
                    "allowed_write_roots": [str(root)],
                }
            ],
        }
    )
    broker = CapabilityBroker(policy, journal)
    context = RunContext(
        run_id=effect_id,
        revision=transition.run.revision,
        state=RunState.DISCOVERY,
        workflow_release_digest=DIGEST_B,
        approval_digest=DIGEST_A,
        actor_class="controller",
        effect_id=effect_id,
        worker_id="sandbox-controller",
    )
    grant = broker.authorize(
        CapabilityRequest("controller", "worker.implementation", str(root), "write"),
        context,
    )
    launcher = WorkerLauncher(broker, codex_executable=str(CODEX))
    try:
        result = launcher.run(
            WorkerTask(WorkerKind.IMPLEMENTATION, root, prompt), grant
        )
        return result, broker.decisions
    finally:
        journal.close()


def command_events(jsonl: str) -> tuple[dict[str, object], ...]:
    events: list[dict[str, object]] = []
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            events.append(item)
    return tuple(events)


@pytest.fixture
def sandbox_base() -> Path:
    """Place denial probes outside macOS sandbox's globally writable temp roots."""
    checkout = Path(__file__).parents[3]
    with tempfile.TemporaryDirectory(prefix=".cdd-sandbox-", dir=checkout) as directory:
        yield Path(directory)


def test_real_codex_workspace_sandbox_allows_inside_and_denies_escape_and_network(
    tmp_path: Path, sandbox_base: Path
) -> None:
    """Would fail if real Codex could bypass write-root or direct-network isolation."""
    assert CODEX.is_file(), "real Codex CLI binary is unavailable"
    root = sandbox_base / "worktree"
    root.mkdir()
    initialize_git(root)

    allowed, _ = run_worker(
        tmp_path,
        root,
        "allowed-write",
        "Run exactly this shell command, then stop: printf 'allowed\\n' > allowed.txt",
    )
    assert allowed.effect.status is DispatchStatus.COMPLETED, allowed.effect.stdout
    assert (root / "allowed.txt").read_text(encoding="utf-8") == "allowed\n"
    assert "allowed.txt" in allowed.changed_paths
    assert any(
        "allowed.txt" in str(event.get("command", ""))
        for event in command_events(allowed.effect.stdout)
    ), allowed.effect.stdout

    outside = sandbox_base / "outside.txt"
    escaped, escape_decisions = run_worker(
        tmp_path,
        root,
        "outside-write",
        f"Run exactly this shell command, then stop: printf 'escaped\\n' > {outside}",
    )
    assert escaped.effect.status is DispatchStatus.COMPLETED, escaped.effect.stdout
    escape_events = command_events(escaped.effect.stdout)
    matching_escape_events = tuple(
        event
        for event in escape_events
        if str(outside) in str(event.get("command", ""))
        and event.get("status") != "in_progress"
    )
    assert all(
        event.get("exit_code") not in (0, None) for event in matching_escape_events
    ), escaped.effect.stdout
    assert outside.exists() is False
    assert escape_decisions[-1].allowed is True

    received_posts: list[bytes] = []

    class Recorder(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            received_posts.append(self.rfile.read(length))
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        networked, _ = run_worker(
            tmp_path,
            root,
            "network-post",
            "Run exactly this shell command, then stop: "
            f"/usr/bin/curl -fsS -X POST --data sandbox-probe http://127.0.0.1:{port}/mutation",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert networked.effect.status is DispatchStatus.COMPLETED, networked.effect.stdout
    network_events = command_events(networked.effect.stdout)
    assert any(
        "sandbox-probe" in str(event.get("command", "")) for event in network_events
    ), networked.effect.stdout
    assert all(
        event.get("exit_code") not in (0, None)
        for event in network_events
        if "sandbox-probe" in str(event.get("command", ""))
        and event.get("status") != "in_progress"
    ), networked.effect.stdout
    assert received_posts == []
