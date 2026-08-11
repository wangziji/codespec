from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from codex_contract_delivery.approvals import (
    ApprovalRecord,
    ApprovalVerifier,
    ChangeLevel,
    ContractNode,
    classify_change,
)
from codex_contract_delivery.canonical import load_yaml

FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"


def _record() -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="gate-two",
        actor="design-lead",
        role="design",
        decision="approved",
        timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
        baseline_digest="a" * 64,
        effective_contract_digest="b" * 64,
        penpot_digest="c" * 64,
        plan_digest="d" * 64,
        workflow_release_digest="e" * 64,
        release_digest="f" * 64,
        canary_digest="0" * 64,
    )


def test_changed_penpot_digest_invalidates_gate_two() -> None:
    """Would fail if approvals remained valid after an approved dependency changed."""
    dependencies = dict(_record().dependencies) | {"penpot": "new-digest"}
    result = ApprovalVerifier().verify(_record(), dependencies)

    assert result.valid is False
    assert result.invalidated_dependencies == ("penpot",)
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-STALE-DEPENDENCY"]


def test_approval_verifier_reports_every_changed_bound_dependency() -> None:
    """Would fail if invalidation hid one changed dependency behind another."""
    result = ApprovalVerifier().verify(
        _record(),
        dict(_record().dependencies)
        | {"baseline": "new", "penpot": "new", "workflow_release": "new"},
    )

    assert result.invalidated_dependencies == ("baseline", "penpot", "workflow_release")


def test_approval_verifier_invalidates_missing_bound_dependency() -> None:
    """Would fail if verification accepted an approval without all of its bound inputs."""
    dependencies = dict(_record().dependencies)
    del dependencies["canary"]

    result = ApprovalVerifier().verify(_record(), dependencies)

    assert result.valid is False
    assert result.invalidated_dependencies == ("canary",)
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-MISSING-DEPENDENCY"]


def test_approval_verifier_invalidates_unbound_actual_dependency() -> None:
    """Would fail if a verifier ignored an actual dependency the approval never bound."""
    result = ApprovalVerifier().verify(_record(), dict(_record().dependencies) | {"surprise": "x"})

    assert result.valid is False
    assert result.invalidated_dependencies == ("surprise",)
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-EXTRA-DEPENDENCY"]


def test_approval_verifier_invalidates_stale_bound_dependency() -> None:
    """Would fail if a same-key digest change did not invalidate an approval."""
    result = ApprovalVerifier().verify(
        _record(), load_yaml(FIXTURES / "stale-approval" / "dependencies.yaml")
    )

    assert result.valid is False
    assert result.invalidated_dependencies == ("release",)
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-STALE-DEPENDENCY"]


def test_unknown_node_kind_is_highest_change_level() -> None:
    """Would fail if a caller could downgrade an ambiguous contract change."""
    assert classify_change((ContractNode("mystery:1", "mystery", {"v": 1}, "x"),)) is ChangeLevel.L2


def test_evidence_only_change_is_lowest_change_level() -> None:
    """Would fail if non-contract evidence changes unnecessarily escalated approval."""
    assert classify_change((ContractNode("evidence:1", "evidence", {"v": 1}, "x"),)) is ChangeLevel.L0


def test_empty_change_is_highest_change_level() -> None:
    """Would fail if an empty, therefore ambiguous change set bypassed review."""
    assert classify_change(()) is ChangeLevel.L2


def test_contract_node_does_not_expose_mutable_nested_value() -> None:
    """Would fail if frozen graph nodes still exposed nested mutable payloads."""
    node = ContractNode("evidence:1", "evidence", {"nested": {"items": ["x"]}}, "x")

    with pytest.raises(TypeError):
        node.value["nested"]["items"][0] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"approval_id": ""}, "approval_id"),
        ({"actor": ""}, "actor"),
        ({"actor": 1}, "actor"),
        ({"role": ""}, "role"),
        ({"role": 1}, "role"),
        ({"decision": "maybe"}, "decision"),
        ({"decision": 1}, "decision"),
        ({"timestamp": datetime(2026, 8, 11, tzinfo=timezone.utc).replace(tzinfo=None)}, "timestamp"),
        ({"timestamp": "x"}, "timestamp"),
        ({"baseline_digest": "bad"}, "digest"),
        ({"baseline_digest": 1}, "digest"),
    ],
)
def test_approval_record_rejects_invalid_bound_input(change: dict[str, object], message: str) -> None:
    """Would fail if malformed approval identity or digest bindings were accepted."""
    values = _record().__dict__ | change

    with pytest.raises(ValueError, match=message):
        ApprovalRecord(**values)


def test_rejected_approval_is_never_valid() -> None:
    """Would fail if a rejected decision could pass verification with matching inputs."""
    rejected = ApprovalRecord(**(_record().__dict__ | {"decision": "rejected"}))

    result = ApprovalVerifier().verify(rejected, rejected.dependencies)

    assert result.valid is False
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-REJECTED"]
