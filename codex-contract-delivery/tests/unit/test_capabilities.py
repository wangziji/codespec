from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
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
    ReconciliationOutcome,
    StaleFence,
    TransitionRequest,
)
from codex_contract_delivery.schema import SchemaRegistry
from codex_contract_delivery.state_machine import RunEvent, RunState

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
PRINTF = str(Path("/usr/bin/printf").resolve())
ENV = str(Path("/usr/bin/env").resolve())


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def policy_record(
    root: Path,
    *,
    executable: str = PRINTF,
    capability: str = "local.execute",
    operation: str = "write",
    resource_pattern: str | None = None,
    allowed_environment_names: list[str] | None = None,
    timeout_seconds: int = 30,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "workflow_release_digest": DIGEST_B,
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
                "timeout_seconds": timeout_seconds,
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
        "capability": "local.execute",
        "resource": str(root),
        "operation": "write",
        "requested_argv": (PRINTF, "ok"),
        "task_fingerprint": DIGEST_C,
    }
    values.update(changes)
    return CapabilityRequest(**values)


def worker_argv(root: Path) -> tuple[str, ...]:
    return (
        PRINTF,
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


def test_worker_success_near_policy_timeout_keeps_commit_authority(
    tmp_path: Path,
) -> None:
    """Would fail if worker runtime consumed the authority reserved for commit."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    observed_timeouts: list[object] = []

    def near_timeout(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed_timeouts.append(kwargs["timeout"])
        clock.advance(timedelta(seconds=29))
        return subprocess.CompletedProcess(argv, 0, "", "")

    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(tmp_path, capability="worker.implementation")
        ),
        journal,
        clock=clock,
        process_runner=near_timeout,
    )
    command = worker_argv(tmp_path)
    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=command,
        ),
        context,
    )
    stage_ref = "effect-stage://sha256/" + "a" * 64

    def commit(prepared: object, authority_check: object) -> str:
        assert prepared == "prepared"
        assert callable(authority_check)
        authority_check(29.0)
        return "committed"

    result, validation = broker._dispatch(
        grant,
        command,
        result_preparer=lambda _completed: (stage_ref, "prepared"),
        result_committer=commit,
    )

    assert observed_timeouts == [30]
    assert result.status is DispatchStatus.COMPLETED
    assert validation == "committed"
    assert journal.get_effect("run-1", "effect-1").state is EffectState.COMPLETED
    journal.close()


def test_worker_grant_and_lease_share_the_bounded_commit_expiry(
    tmp_path: Path,
) -> None:
    """Would fail if either grant or fence expired inside the commit budget."""
    clock = MutableClock()
    issued_at = clock.now
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(
                tmp_path,
                capability="worker.implementation",
                timeout_seconds=1,
            )
        ),
        journal,
        clock=clock,
    )
    command = worker_argv(tmp_path)
    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=command,
        ),
        context,
    )
    stage_ref = "effect-stage://sha256/" + "a" * 64
    journal.record_effect(grant.effect_id, grant.fence, EffectState.STARTED, None)
    journal.record_effect(grant.effect_id, grant.fence, EffectState.PREPARED, stage_ref)

    clock.advance(timedelta(seconds=0.5))
    broker._validate_grant(grant, minimum_validity_seconds=29.0)
    journal.record_effect(
        grant.effect_id,
        grant.fence,
        EffectState.PREPARED,
        stage_ref,
        minimum_lease_ttl=timedelta(seconds=29),
    )

    clock.advance(timedelta(seconds=29.5))
    assert clock.now == issued_at + timedelta(seconds=30)
    with pytest.raises(CapabilityDenied, match="grant expired"):
        broker._validate_grant(grant)
    with pytest.raises(StaleFence, match="not current"):
        journal.record_effect(
            grant.effect_id, grant.fence, EffectState.PREPARED, stage_ref
        )
    journal.close()


def test_extended_worker_authority_does_not_extend_process_timeout(
    tmp_path: Path,
) -> None:
    """Would fail if commit authority lengthened worker execution itself."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    observed_timeouts: list[object] = []

    def timeout(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed_timeouts.append(kwargs["timeout"])
        clock.advance(timedelta(seconds=1.1))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(
                tmp_path,
                capability="worker.implementation",
                timeout_seconds=1,
            )
        ),
        journal,
        clock=clock,
        process_runner=timeout,
    )
    command = worker_argv(tmp_path)
    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=command,
        ),
        context,
    )

    result = broker.dispatch(grant, command)

    assert observed_timeouts == [1]
    assert result.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert journal.get_effect("run-1", "effect-1").state is EffectState.STARTED
    journal.close()


def test_prepared_adoption_requires_matching_stage_and_records_audit(
    tmp_path: Path,
) -> None:
    """Would fail if a new fence could adopt an unrelated or unaudited stage."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    capability_request = request(tmp_path)
    first = broker.authorize(capability_request, context)
    prior = "effect-stage://sha256/" + "a" * 64
    journal.record_effect(first.effect_id, first.fence, EffectState.STARTED, None)
    journal.record_effect(first.effect_id, first.fence, EffectState.PREPARED, prior)
    journal.record_reconciliation(
        first.effect_id,
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://host-before-manifest",
    )

    with pytest.raises(CapabilityDenied, match="durable stage"):
        broker.authorize_prepared_adoption(
            capability_request,
            context,
            "effect-stage://sha256/" + "b" * 64,
        )

    adopted = broker.authorize_prepared_adoption(capability_request, context, prior)

    assert adopted.fence > first.fence
    assert broker.decisions[-1].allowed is True
    assert broker.decisions[-1].reason_code == "prepared-adoption-authorized"
    journal.close()


def test_prepared_adoption_commits_only_after_new_fence_is_durable(
    tmp_path: Path,
) -> None:
    """Would fail if adopted host mutation preceded its new-fence journal intent."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    capability_request = request(tmp_path)
    first = broker.authorize(capability_request, context)
    prior = "effect-stage://sha256/" + "a" * 64
    adopted_ref = "effect-stage://sha256/" + "b" * 64
    journal.record_effect(first.effect_id, first.fence, EffectState.STARTED, None)
    journal.record_effect(first.effect_id, first.fence, EffectState.PREPARED, prior)
    journal.record_reconciliation(
        first.effect_id,
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://host-before-manifest",
    )
    grant = broker.authorize_prepared_adoption(capability_request, context, prior)
    observed: list[tuple[EffectState, str | None]] = []

    def commit(prepared: object, authority_check: object) -> str:
        assert prepared == "stage-object"
        assert callable(authority_check)
        authority_check(1.0)
        effect = journal.get_effect("run-1", "effect-1")
        assert effect is not None
        observed.append((effect.state, effect.evidence_ref))
        return "committed"

    result, validation = broker.commit_prepared_adoption(
        grant,
        prior,
        adopted_ref,
        "stage-object",
        commit,
    )

    assert observed == [(EffectState.PREPARED, adopted_ref)]
    assert result.status is DispatchStatus.COMPLETED
    assert validation == "committed"
    effect = journal.get_effect("run-1", "effect-1")
    assert effect is not None
    assert effect.state is EffectState.COMPLETED
    assert effect.evidence_ref == adopted_ref
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
    grant = broker.authorize(
        request(approved, requested_argv=(PRINTF, "should-not-run")), context
    )
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
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted-env"
    trusted_root.mkdir()
    environment_dump = trusted_root / "environment-dump"
    environment_dump.write_text(
        f"#!/bin/sh\nexec {ENV}\n",
        encoding="utf-8",
    )
    environment_dump.chmod(0o755)
    policy = policy_record(
        tmp_path,
        executable=str(environment_dump),
        operation="read",
        capability="inspect",
        allowed_environment_names=allowed,
    )
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy), journal, clock=clock
    )
    grant = broker.authorize(
        request(
            tmp_path,
            capability="inspect",
            operation="read",
            requested_argv=(str(environment_dump),),
        ),
        context,
    )

    result = broker.dispatch(grant, (str(environment_dump),))

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
            requested_argv=(PRINTF, "ok"),
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
    grant = broker.authorize(
        request(tmp_path, requested_argv=(PRINTF, "done")), context
    )

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
    grant = broker.authorize(
        request(tmp_path, requested_argv=(PRINTF, "slow")), context
    )

    result = broker.dispatch(grant, (PRINTF, "slow"))

    assert result.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert result.effect_id == "effect-1"
    assert result.fence == grant.fence
    assert journal.get_effect("run-1", "effect-1").state is EffectState.STARTED
    with pytest.raises(CapabilityDenied, match="already dispatched"):
        broker.dispatch(grant, (PRINTF, "slow"))
    journal.close()


def test_policy_release_is_live_authority_and_invalidates_old_grant(
    tmp_path: Path,
) -> None:
    """Would fail if the caller could self-report a release or reuse a stale grant."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    current = policy_record(tmp_path)
    current["workflow_release_digest"] = DIGEST_B
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(current), journal, clock=clock
    )
    grant = broker.authorize(request(tmp_path), context)

    switched = policy_record(tmp_path)
    switched["workflow_release_digest"] = DIGEST_C
    broker.policy = CapabilityPolicy.from_mapping(switched)

    with pytest.raises(CapabilityDenied, match="release"):
        broker.dispatch(grant, (PRINTF, "ok"))
    with pytest.raises(CapabilityDenied, match="release"):
        broker.authorize(request(tmp_path), context)
    journal.close()


def test_authorization_denial_audit_contains_nonsecret_authority_context(
    tmp_path: Path,
) -> None:
    """Would fail if broker-owned denial evidence lacked the deciding context."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)), journal, clock=clock
    )
    denied = request(tmp_path, capability="external.network")

    with pytest.raises(CapabilityDenied):
        broker.authorize(denied, context)

    decision = broker.decisions[-1]
    assert decision.allowed is False
    assert decision.capability == "external.network"
    assert decision.resource == str(tmp_path)
    assert decision.run_id == "run-1"
    assert decision.revision == 1
    assert decision.policy_digest == broker.policy.digest
    assert not hasattr(decision, "requested_argv")
    journal.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_environment_names", ["PATH", "PATH"]),
        ("allowed_write_roots", ["ROOT", "ROOT"]),
    ],
)
def test_runtime_rejects_duplicate_scopes_like_schema(
    tmp_path: Path, field: str, value: list[str]
) -> None:
    """Would fail while runtime silently normalized an ambiguous duplicate scope."""
    record = policy_record(tmp_path)
    record["policies"][0][field] = [
        str(tmp_path) if item == "ROOT" else item for item in value
    ]

    with pytest.raises(PolicyInvalid, match="duplicate"):
        CapabilityPolicy.from_mapping(record)


def test_policy_rejects_executable_inside_worker_write_scope(tmp_path: Path) -> None:
    """Would fail if a worker could replace the executable it is about to run."""
    executable = tmp_path / "worker-writable-tool"
    shutil.copyfile(PRINTF, executable)
    executable.chmod(0o755)

    with pytest.raises(PolicyInvalid, match="executable.*write root"):
        CapabilityPolicy.from_mapping(
            policy_record(tmp_path, executable=str(executable))
        )


@pytest.mark.parametrize("mutation", ["replace", "symlink", "in-place"])
def test_dispatch_rejects_executable_identity_mutation(
    tmp_path: Path, mutation: str
) -> None:
    """Would fail if an authorized executable could be replaced before spawn."""
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted_root.mkdir()
    executable = trusted_root / "approved-tool"
    shutil.copyfile(PRINTF, executable)
    executable.chmod(0o755)
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(tmp_path, executable=str(executable))
        ),
        journal,
        clock=clock,
        process_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, "", ""
        ),
    )
    grant = broker.authorize(
        request(tmp_path, requested_argv=(str(executable), "ok")), context
    )

    if mutation == "replace":
        replacement = trusted_root / "replacement"
        shutil.copyfile(ENV, replacement)
        replacement.chmod(0o755)
        os.replace(replacement, executable)
    elif mutation == "symlink":
        executable.unlink()
        executable.symlink_to(ENV)
    else:
        with executable.open("r+b") as stream:
            first = stream.read(1)
            stream.seek(0)
            stream.write(b"X" if first != b"X" else b"Y")

    with pytest.raises(CapabilityDenied, match="executable"):
        broker.dispatch(grant, (str(executable), "ok"))
    assert journal.get_effect("run-1", "effect-1").state is EffectState.INTENT
    journal.close()


def test_dispatch_executes_immutable_copy_after_path_replacement_race(
    tmp_path: Path,
) -> None:
    """Would fail if verified fds were evidence but exec still selected the path."""
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted-race"
    trusted_root.mkdir()
    executable = trusted_root / "race-tool"
    executable.write_text("#!/bin/sh\nprintf ORIGINAL", encoding="utf-8")
    executable.chmod(0o755)
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)

    def replace_after_validation(
        argv: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        executable.write_text("#!/bin/sh\nprintf REPLACED", encoding="utf-8")
        executable.chmod(0o755)
        kwargs.pop("check", None)
        return subprocess.run(argv, check=False, **kwargs)

    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(tmp_path, executable=str(executable))
        ),
        journal,
        clock=clock,
        process_runner=replace_after_validation,
    )
    grant = broker.authorize(
        request(tmp_path, requested_argv=(str(executable),)), context
    )

    result = broker.dispatch(grant, (str(executable),))

    assert result.status is DispatchStatus.COMPLETED
    assert result.stdout == "ORIGINAL"
    journal.close()


def test_lease_covers_latest_legal_dispatch_deadline(tmp_path: Path) -> None:
    """Would fail if a delayed but valid grant could lose its fence mid-process."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)),
        journal,
        clock=clock,
        process_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, "", ""
        ),
    )
    grant = broker.authorize(request(tmp_path), context)
    assert grant.lease_expires_at >= grant.expires_at + timedelta(seconds=30.5)

    clock.advance(timedelta(seconds=29))
    result = broker.dispatch(grant, (PRINTF, "ok"))

    assert result.status is DispatchStatus.COMPLETED
    assert journal.get_effect("run-1", "effect-1").state is EffectState.COMPLETED
    journal.close()


def test_timeout_kills_entire_process_group_before_return(tmp_path: Path) -> None:
    """Would fail if a timed-out grandchild could mutate state after reconciliation."""
    marker = tmp_path / "late-write"
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted_root.mkdir()
    executable = trusted_root / "process-tree"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "if os.fork() == 0:\n"
        "    time.sleep(2)\n"
        f"    open({str(marker)!r}, 'w').write('late')\n"
        "    os._exit(0)\n"
        "time.sleep(20)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    journal = Journal.open(tmp_path / "tree.sqlite3")
    result = journal.transition(
        TransitionRequest(
            "run-1",
            0,
            RunEvent.DISCOVER,
            {},
            EffectIntent("effect-1", "worker"),
        )
    )
    context = RunContext(
        "run-1",
        result.run.revision,
        RunState.DISCOVERY,
        DIGEST_B,
        DIGEST_A,
        "controller",
        "effect-1",
        "controller-1",
    )
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(tmp_path, executable=str(executable), timeout_seconds=1)
        ),
        journal,
    )
    grant = broker.authorize(
        request(tmp_path, requested_argv=(str(executable),)), context
    )

    effect = broker.dispatch(grant, (str(executable),))
    time.sleep(2.1)

    assert effect.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert not marker.exists()
    journal.close()


def test_timeout_kills_term_ignoring_child_after_group_leader_exits(
    tmp_path: Path,
) -> None:
    """Would fail if reaping the leader was mistaken for group extinction."""
    marker = tmp_path / "late-child-write"
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted-child"
    trusted_root.mkdir()
    executable = trusted_root / "leader-exits"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import os, signal, time\n"
        "if os.fork() == 0:\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    time.sleep(2)\n"
        f"    open({str(marker)!r}, 'w').write('late')\n"
        "    os._exit(0)\n"
        "time.sleep(20)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(
            policy_record(
                tmp_path,
                executable=str(executable),
                timeout_seconds=1,
            )
        ),
        journal,
        clock=clock,
    )
    grant = broker.authorize(
        request(tmp_path, requested_argv=(str(executable),)), context
    )

    result = broker.dispatch(grant, (str(executable),))
    time.sleep(2.1)

    assert result.status is DispatchStatus.RECONCILIATION_REQUIRED
    assert not marker.exists()
    journal.close()


def test_lima_worker_authorization_requires_exact_guest_wrapper_grammar(
    tmp_path: Path,
) -> None:
    """Would fail if direct broker callers could extend the VM worker wrapper."""
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted_root.mkdir()
    limactl = trusted_root / "limactl"
    limactl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    limactl.chmod(0o755)
    prefix = (
        str(limactl),
        "shell",
        "codex-worker",
        "--",
        "/usr/bin/python3",
        "/readonly/vm_guest.py",
        "--workspace-base",
        "/home/mark.guest/.local/share/cdd/workspaces",
    )
    record = policy_record(tmp_path, executable=str(limactl))
    record["policies"][0]["capability"] = "worker.implementation"
    record["policies"][0]["allowed_argv_prefix"] = list(prefix)
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(record), journal, clock=clock
    )
    expected = (
        *prefix,
        "--authority-digest",
        DIGEST_B,
        "--source-snapshot-digest",
        DIGEST_A,
        "--kind",
        "implementation",
        "--task-fingerprint",
        DIGEST_C,
        "--json",
    )

    with pytest.raises(CapabilityDenied, match="worker command|danger"):
        broker.authorize(
            request(
                tmp_path,
                capability="worker.implementation",
                requested_argv=(*expected, "--add-dir", "/tmp"),
            ),
            context,
        )

    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=expected,
        ),
        context,
    )
    assert grant.canonical_argv == expected
    journal.close()


def test_result_validator_denial_is_recorded_in_broker_audit(tmp_path: Path) -> None:
    """Would fail if rejected external output left only unaudited exception evidence."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(policy_record(tmp_path)),
        journal,
        clock=clock,
        process_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, "", ""
        ),
    )
    grant = broker.authorize(request(tmp_path), context)

    with pytest.raises(RuntimeError, match="export denied"):
        broker._dispatch(
            grant,
            (PRINTF, "ok"),
            result_validator=lambda completed: (_ for _ in ()).throw(
                RuntimeError("export denied")
            ),
        )

    decision = broker.decisions[-1]
    assert decision.allowed is False
    assert decision.reason_code == "result-policy-violation"
    assert decision.capability == "local.execute"
    assert decision.run_id == "run-1"
    assert journal.get_effect("run-1", "effect-1").state is EffectState.COMPLETED
    journal.close()


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (2, "", DispatchStatus.FAILED),
        (
            0,
            (
                '{"item":{"type":"command_execution","status":"failed",'
                '"exit_code":1,"aggregated_output":"Operation not permitted"}}\n'
            ),
            DispatchStatus.DENIED,
        ),
    ],
)
def test_failed_or_denied_worker_never_invokes_export_validator(
    tmp_path: Path,
    returncode: int,
    stdout: str,
    expected: DispatchStatus,
) -> None:
    """Would fail if a partial patch could be imported from a failed guest."""
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted"
    trusted_root.mkdir()
    executable = trusted_root / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    command = (
        str(executable),
        "exec",
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(tmp_path),
        "--json",
        "-",
    )
    record = policy_record(
        tmp_path,
        executable=str(executable),
        capability="worker.implementation",
    )
    record["policies"][0]["allowed_argv_prefix"] = [str(executable), "exec"]
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(record),
        journal,
        clock=clock,
        process_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, returncode, stdout, ""
        ),
    )
    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=command,
        ),
        context,
    )
    validator_calls = 0

    def validator(completed: subprocess.CompletedProcess[str]) -> object:
        nonlocal validator_calls
        validator_calls += 1
        return object()

    result, validation = broker._dispatch(
        grant,
        command,
        result_validator=validator,
    )

    assert result.status is expected
    assert validation is None
    assert validator_calls == 0
    journal.close()


def test_typed_worker_denial_appends_broker_denial_and_matching_evidence(
    tmp_path: Path,
) -> None:
    """Would fail if a sandbox denial left the last audit decision authorized."""
    clock = MutableClock()
    journal, context = seed(tmp_path, clock)
    stdout = (
        '{"item":{"type":"command_execution","status":"failed",'
        '"exit_code":1,"aggregated_output":"Operation not permitted"}}\n'
    )
    trusted_root = tmp_path.parent / f"{tmp_path.name}-trusted-denial"
    trusted_root.mkdir()
    executable = trusted_root / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    command = (
        str(executable),
        "exec",
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--cd",
        str(tmp_path),
        "--json",
        "-",
    )
    record = policy_record(
        tmp_path,
        executable=str(executable),
        capability="worker.implementation",
    )
    record["policies"][0]["allowed_argv_prefix"] = [str(executable), "exec"]
    broker = CapabilityBroker(
        CapabilityPolicy.from_mapping(record),
        journal,
        clock=clock,
        process_runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, stdout, ""
        ),
    )
    grant = broker.authorize(
        request(
            tmp_path,
            capability="worker.implementation",
            requested_argv=command,
        ),
        context,
    )

    result = broker.dispatch(grant, command)

    assert result.status is DispatchStatus.DENIED
    decision = broker.decisions[-1]
    assert decision.allowed is False
    assert decision.reason_code == "worker-sandbox-denied"
    effect = journal.get_effect("run-1", "effect-1")
    assert effect is not None
    assert effect.state is EffectState.COMPLETED
    assert effect.evidence_ref == result.evidence_ref
    journal.close()
