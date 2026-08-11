from __future__ import annotations

from datetime import datetime, timezone

from codex_contract_delivery.approvals import (
    ApprovalRecord,
    ApprovalVerifier,
    ChangeLevel,
    ContractNode,
    classify_change,
)


def _record() -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="gate-two",
        actor="design-lead",
        role="design",
        decision="approved",
        timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
        baseline_digest="baseline",
        effective_contract_digest="effective",
        penpot_digest="old-digest",
        plan_digest="plan",
        workflow_release_digest="workflow",
        release_digest="release",
        canary_digest="canary",
    )


def test_changed_penpot_digest_invalidates_gate_two() -> None:
    """Would fail if approvals remained valid after an approved dependency changed."""
    result = ApprovalVerifier().verify(_record(), {"penpot": "new-digest"})

    assert result.valid is False
    assert result.invalidated_dependencies == ("penpot",)
    assert [finding.code for finding in result.findings] == ["CDD-APPROVAL-STALE-DEPENDENCY"]


def test_approval_verifier_reports_every_changed_bound_dependency() -> None:
    """Would fail if invalidation hid one changed dependency behind another."""
    result = ApprovalVerifier().verify(
        _record(), {"baseline": "new", "penpot": "new", "workflow_release": "new"}
    )

    assert result.invalidated_dependencies == ("baseline", "penpot", "workflow_release")


def test_unknown_node_kind_is_highest_change_level() -> None:
    """Would fail if a caller could downgrade an ambiguous contract change."""
    assert classify_change((ContractNode("mystery:1", "mystery", {"v": 1}, "x"),)) is ChangeLevel.L2


def test_evidence_only_change_is_lowest_change_level() -> None:
    """Would fail if non-contract evidence changes unnecessarily escalated approval."""
    assert classify_change((ContractNode("evidence:1", "evidence", {"v": 1}, "x"),)) is ChangeLevel.L0
