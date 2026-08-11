"""Dependency-bound approval records and conservative change classification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .models import Finding


class ChangeLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


@dataclass(frozen=True)
class ContractNode:
    node_id: str
    kind: str
    value: Mapping[str, object]
    origin: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", MappingProxyType(dict(self.value)))


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    actor: str
    role: str
    decision: str
    timestamp: datetime
    baseline_digest: str
    effective_contract_digest: str
    penpot_digest: str
    plan_digest: str
    workflow_release_digest: str
    release_digest: str | None = None
    canary_digest: str | None = None

    @property
    def dependencies(self) -> Mapping[str, str]:
        values = {
            "baseline": self.baseline_digest,
            "effective_contract": self.effective_contract_digest,
            "penpot": self.penpot_digest,
            "plan": self.plan_digest,
            "workflow_release": self.workflow_release_digest,
        }
        if self.release_digest is not None:
            values["release"] = self.release_digest
        if self.canary_digest is not None:
            values["canary"] = self.canary_digest
        return MappingProxyType(values)


@dataclass(frozen=True)
class ApprovalResult:
    valid: bool
    invalidated_dependencies: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()


class ApprovalVerifier:
    """Invalidate an approval whenever any dependency bound by it changes."""

    def verify(self, record: ApprovalRecord, dependencies: Mapping[str, str]) -> ApprovalResult:
        invalidated = tuple(
            name
            for name, approved_digest in record.dependencies.items()
            if name in dependencies and dependencies[name] != approved_digest
        )
        findings = tuple(
            Finding(
                "CDD-APPROVAL-STALE-DEPENDENCY",
                f"Approval dependency changed: {name}",
                name,
            )
            for name in invalidated
        )
        return ApprovalResult(not invalidated, invalidated, findings)


_L0_KINDS = frozenset({"evidence", "learning-signal", "documentation"})
_L1_KINDS = frozenset({"scenario", "api", "architecture", "penpot", "verification"})
_L2_KINDS = frozenset(
    {"baseline", "policy", "environment", "workflow-release", "release", "canary", "model-policy"}
)


def classify_change(changed_nodes: Iterable[ContractNode]) -> ChangeLevel:
    """Derive approval level from authoritative node kinds, never caller labels."""
    level = ChangeLevel.L0
    for node in changed_nodes:
        if node.kind in _L2_KINDS or node.kind not in _L0_KINDS | _L1_KINDS:
            return ChangeLevel.L2
        if node.kind in _L1_KINDS:
            level = ChangeLevel.L1
    return level
