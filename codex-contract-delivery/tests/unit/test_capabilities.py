from __future__ import annotations

import dataclasses
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from codex_contract_delivery.capabilities import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityPolicy,
    CapabilityRequest,
    DispatchStatus,
    PolicyInvalid,
    RunContext,
)
from codex_contract_delivery.journal import (
    EffectIntent,
    EffectState,
    Journal,
    TransitionRequest,
)
from codex_contract_delivery.schema import SchemaRegistry
from codex_contract_delivery.state_machine import RunEvent, RunState

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
PRINTF = str(Path("/usr/bin/printf").resolve())
ENV = str(Path("/usr/bin/env").resolve())


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def policy_record(
    root: Path,
    *,
    executable: str = PRINTF,
    capability: str = "worker.implementation",
    operation: str = "write",
    resource_pattern: str | None = None,
    allowed_environment_names: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "policies": [
            {
                "policy_id": "worker-implementation-v1",
                "capability": capability,
                "operation": operation,
                "resource_pattern": resource_pattern or str(root),
                "allowed_argv_prefix": [executable],
                "required_run_state": "discovery",
                "approval_digest": DIGEST_A,
                "actor_class": "controller",
                "timeout_seconds": 30,
                "idempotency_strategy": "effect-id",
                "reconciliation_strategy": "journal-probe",
                "allowed_environment_names": allowed_environment_names or [],
                "allowed_write_roots": [str(root)],
            }
        ],
    }


def seed(
    tmp_path: Path,
    clock: MutableClock,
    *,
    effect_id: str = "effect-1",
) -> tuple[Journal, RunContext]:
    journal = Journal.open(tmp_path / "journal.sqlite3", clock=clock)
    result = journal.transition(
        TransitionRequest(
            "run-1",
            0,
            RunEvent.DISCOVER,
            {},
            EffectIntent(effect_id, "worker"),
        )
    )
    context = RunContext(
        run_id="run-1",
        revision=result.run.revision,
        state=RunState.DISCOVERY,
        workflow_release_digest=DIGEST_B,
        approval_digest=DIGEST_A,
        actor_class="controller",
        effect_id=effect_id,
        worker_id="controller-1",
    )
    return journal, context


def request(root: Path, **changes: object) -> CapabilityRequest:
    values: dict[str, object] = {
        "source": "controller",
        "capability": "worker.implementation",
        "resource": str(root),
        "operation": "write",
    }
    values.update(changes)
    return CapabilityRequest(**values)


def test_extension_payload_cannot_dispatch_mutation(tmp_path: Path) -> None:
    """Would fail if untrusted prompt provenance could acquire write authority."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )

    with pytest.raises(
        CapabilityDenied,
        match="extension payloads cannot request mutating capabilities",
    ):
        broker.authorize(request(tmp_path, source="extension"), context)

    assert broker.decisions[-1].allowed is False
    assert broker.decisions[-1].reason_code == "untrusted-source-mutation"
    journal.close()


def test_unknown_policy_fields_and_unsafe_patterns_fail_closed(tmp_path: Path) -> None:
    """Would fail if misspelled controls or regex/traversal patterns were ignored."""
    unknown = policy_record(tmp_path)
    unknown["policies"][0]["allow_everything"] = True
    with pytest.raises(PolicyInvalid, match="unknown field"):
        CapabilityPolicy.from_mapping(unknown)

    unsafe = policy_record(tmp_path, resource_pattern=str(tmp_path / "(a+)+"))
    with pytest.raises(PolicyInvalid, match="resource_pattern"):
        CapabilityPolicy.from_mapping(unsafe)

    traversal = policy_record(
        tmp_path, resource_pattern=str(tmp_path / ".." / "escape")
    )
    with pytest.raises(PolicyInvalid, match="resource_pattern"):
        CapabilityPolicy.from_mapping(traversal)

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    symlink_scope = policy_record(real_root)
    symlink_scope["policies"][0]["allowed_write_roots"] = [str(linked_root)]
    with pytest.raises(PolicyInvalid, match="symlink"):
        CapabilityPolicy.from_mapping(symlink_scope)

    invalid_environment = policy_record(tmp_path)
    invalid_environment["policies"][0]["allowed_environment_names"] = ["BAD-NAME"]
    with pytest.raises(PolicyInvalid, match="allowed_environment_names"):
        CapabilityPolicy.from_mapping(invalid_environment)


def test_policy_schema_rejects_unknown_nested_field(tmp_path: Path) -> None:
    """Would fail if the published contract allowed controls the runtime ignores."""
    value = policy_record(tmp_path)
    value["policies"][0]["allow_everything"] = True
    registry = SchemaRegistry(Path(__file__).parents[2] / "schemas")

    findings = registry.validate("capability-policy", value)

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-ADDITIONAL-PROPERTY", "policies.0.allow_everything")
    ]


def test_authorize_returns_immutable_content_addressed_short_lived_grant(
    tmp_path: Path,
) -> None:
    """Would fail if a grant could be edited or detached from its authority inputs."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )

    grant = broker.authorize(request(tmp_path), context)

    assert grant.verify_digest() is True
    assert grant.expires_at == clock.now + timedelta(seconds=30)
    assert grant.effect_id == "effect-1"
    assert grant.fence == 1
    assert grant.run_revision == 1
    assert grant.workflow_release_digest == DIGEST_B
    assert grant.approval_digest == DIGEST_A
    assert grant.allowed_write_roots == (str(tmp_path.resolve()),)
    with pytest.raises(dataclasses.FrozenInstanceError):
        grant.resource = "prod"
    journal.close()


@pytest.mark.parametrize(
    ("context_change", "message"),
    [
        ({"approval_digest": DIGEST_B}, "approval digest"),
        ({"actor_class": "worker"}, "actor class"),
        ({"state": RunState.IMPLEMENTATION}, "run state"),
    ],
)
def test_authorize_denies_context_drift(
    tmp_path: Path, context_change: dict[str, object], message: str
) -> None:
    """Would fail if policy-bound context could be supplied by the wrong authority."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    changed = dataclasses.replace(context, **context_change)

    with pytest.raises(CapabilityDenied, match=message):
        broker.authorize(request(tmp_path), changed)
    journal.close()


def test_authorize_denies_resource_traversal_and_prefix_confusion(
    tmp_path: Path,
) -> None:
    """Would fail if lexical prefixes could escape an approved path boundary."""
    approved = tmp_path / "approved"
    approved.mkdir()
    sibling = tmp_path / "approved-evil"
    sibling.mkdir()
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    policy = policy_record(
        approved,
        resource_pattern=f"{approved}/**",
    )
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy), journal, clock=clock
    )

    with pytest.raises(CapabilityDenied, match="resource"):
        broker.authorize(request(sibling), context)
    with pytest.raises(CapabilityDenied, match="resource"):
        broker.authorize(request(approved / ".." / "approved-evil"), context)
    journal.close()


@pytest.mark.parametrize(
    "argv",
    [
        (),
        (PRINTF + "-evil", "hello"),
        (PRINTF, "$(touch /tmp/pwned)"),
        (PRINTF, "$HOME"),
        (PRINTF, "(id)"),
        (PRINTF, "hello; id"),
        (PRINTF, "bad\x00value"),
        (PRINTF, 7),
    ],
)
def test_dispatch_rejects_malformed_or_confused_argv(
    tmp_path: Path, argv: tuple[object, ...]
) -> None:
    """Would fail if dispatch accepted shell syntax, non-strings, or prefix lookalikes."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    grant = broker.authorize(request(tmp_path), context)

    with pytest.raises(CapabilityDenied):
        broker.dispatch(grant, argv)

    assert journal.get_effect("run-1", "effect-1").state is EffectState.INTENT
    journal.close()


def test_dispatch_denies_resource_replaced_by_symlink_after_authorization(
    tmp_path: Path,
) -> None:
    """Would fail if a grant's approved path could be redirected before dispatch."""
    approved = tmp_path / "approved"
    approved.mkdir()
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(approved)), journal, clock=clock
    )
    grant = broker.authorize(request(approved), context)
    moved = tmp_path / "moved"
    approved.rename(moved)
    approved.symlink_to(moved, target_is_directory=True)

    with pytest.raises(CapabilityDenied, match="resource drift"):
        broker.dispatch(grant, (PRINTF, "should-not-run"))

    assert journal.get_effect("run-1", "effect-1").state is EffectState.INTENT
    journal.close()


def test_dispatch_denies_tampered_grant_and_run_revision_drift(tmp_path: Path) -> None:
    """Would fail if content or journal state could change after authorization."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    grant = broker.authorize(request(tmp_path), context)

    with pytest.raises(CapabilityDenied, match="grant digest"):
        broker.dispatch(dataclasses.replace(grant, resource="prod"), (PRINTF, "ok"))

    journal.transition(TransitionRequest("run-1", 1, RunEvent.DRAFT_REQUIREMENTS, {}))
    with pytest.raises(CapabilityDenied, match="run context drift"):
        broker.dispatch(grant, (PRINTF, "ok"))
    assert journal.get_effect("run-1", "effect-1").state is EffectState.INTENT
    journal.close()


def test_dispatch_filters_external_credentials_and_injects_only_effect_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Would fail if an approved process inherited ambient service credentials."""
    for name, value in {
        "CDD_TEST_SAFE": "safe-value",
        "AWS_SECRET_ACCESS_KEY": "not-for-child",
        "GITHUB_TOKEN": "not-for-child",
        "DATABASE_URL": "not-for-child",
        "HTTPS_PROXY": "not-for-child",
        "OPENAI_API_KEY": "not-for-child",
        "SSH_AUTH_SOCK": "not-for-child",
        "CODEX_HOME": "/controlled/codex-home",
    }.items():
        monkeypatch.setenv(name, value)
    allowed = [
        "CDD_TEST_SAFE",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "HTTPS_PROXY",
        "OPENAI_API_KEY",
        "SSH_AUTH_SOCK",
        "CODEX_HOME",
    ]
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    policy = policy_record(
        tmp_path,
        executable=ENV,
        operation="read",
        capability="inspect",
        allowed_environment_names=allowed,
    )
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy), journal, clock=clock
    )
    grant = broker.authorize(
        request(tmp_path, capability="inspect", operation="read"), context
    )

    result = broker.dispatch(grant, (ENV,))

    assert result.status is DispatchStatus.COMPLETED
    assert "CDD_TEST_SAFE=safe-value" in result.stdout
    assert "CODEX_HOME=/controlled/codex-home" in result.stdout
    assert "CDD_IDEMPOTENCY_KEY=effect-1" in result.stdout
    assert "not-for-child" not in result.stdout
    journal.close()


def test_nonfilesystem_mutation_stays_broker_owned_without_fake_write_root(
    tmp_path: Path,
) -> None:
    """Would fail if adapter resources were confused with filesystem write scope."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    policy = policy_record(
        tmp_path,
        capability="github.write",
        operation="write",
        resource_pattern="github://example/repository",
    )
    policy["policies"][0]["allowed_write_roots"] = []
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy), journal, clock=clock
    )

    grant = broker.authorize(
        request(
            tmp_path,
            capability="github.write",
            operation="write",
            resource="github://example/repository",
        ),
        context,
    )

    assert grant.allowed_write_roots == ()
    assert grant.resource == "github://example/repository"
    journal.close()


def test_dispatch_records_started_before_call_and_completion_evidence(
    tmp_path: Path,
) -> None:
    """Would fail if the external process could start before durable STARTED."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)

    def runner(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert kwargs["shell"] is False
        assert journal.get_effect("run-1", "effect-1").state is EffectState.STARTED
        assert kwargs["env"]["CDD_IDEMPOTENCY_KEY"] == "effect-1"
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)),
        journal,
        clock=clock,
        process_runner=runner,
    )
    grant = broker.authorize(request(tmp_path), context)

    result = broker.dispatch(grant, (PRINTF, "done"))

    assert result.status is DispatchStatus.COMPLETED
    assert result.evidence_ref.startswith("effect-result://sha256/")
    assert journal.get_effect("run-1", "effect-1").state is EffectState.COMPLETED
    assert journal.get_effect("run-1", "effect-1").evidence_ref == result.evidence_ref
    journal.close()


def test_dispatch_timeout_enters_typed_reconciliation_without_redispatch(
    tmp_path: Path,
) -> None:
    """Would fail if an ambiguous timeout were treated as safe to retry."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)

    def timeout(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)),
        journal,
        clock=clock,
        process_runner=timeout,
    )
    grant = broker.authorize(request(tmp_path), context)

    result = broker.dispatch(grant, (PRINTF, "slow"))

    assert result.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert result.effect_id == "effect-1"
    assert result.fence == grant.fence
    assert journal.get_effect("run-1", "effect-1").state is EffectState.STARTED
    with pytest.raises(CapabilityDenied, match="already dispatched"):
        broker.dispatch(grant, (PRINTF, "slow"))
    journal.close()
