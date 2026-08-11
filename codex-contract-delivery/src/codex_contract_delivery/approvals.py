"""Dependency-bound approval records and conservative change classification."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from .models import Finding


def freeze_value(value: object) -> object:
    """Recursively freeze contract payloads before they cross a public boundary."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(freeze_value(item) for item in value)
    return value


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
        object.__setattr__(self, "value", freeze_value(self.value))


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

    def __post_init__(self) -> None:
        if not self.actor or not self.role:
            raise ValueError("actor and role must be non-empty")
        if self.decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-qualified RFC3339 time")
        for name, digest in self.dependencies.items():
            if not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ValueError(f"{name} digest must be a lowercase SHA-256 hex digest")

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
        if record.decision == "rejected":
            return ApprovalResult(False, (), (Finding("CDD-APPROVAL-REJECTED", "Approval decision is rejected.", "decision"),))
        bound = record.dependencies
        missing = sorted(set(bound) - set(dependencies))
        extra = sorted(set(dependencies) - set(bound))
        stale = sorted(name for name in set(bound) & set(dependencies) if bound[name] != dependencies[name])
        invalidated = tuple(missing + extra + stale)
        findings = tuple(
            Finding(code, f"Approval dependency {description}: {name}", name)
            for name, code, description in (
                *((name, "CDD-APPROVAL-MISSING-DEPENDENCY", "is missing") for name in missing),
                *((name, "CDD-APPROVAL-EXTRA-DEPENDENCY", "is not bound") for name in extra),
                *((name, "CDD-APPROVAL-STALE-DEPENDENCY", "changed") for name in stale),
            )
        )
        return ApprovalResult(not invalidated, invalidated, findings)


_L0_KINDS = frozenset({"evidence", "learning-signal", "documentation"})
_L1_KINDS = frozenset({"scenario", "api", "architecture", "penpot", "verification"})
_L2_KINDS = frozenset(
    {"baseline", "policy", "environment", "workflow-release", "release", "canary", "model-policy"}
)


def classify_change(changed_nodes: Iterable[ContractNode]) -> ChangeLevel:
    """Derive approval level from authoritative node kinds, never caller labels."""
    materialized = tuple(changed_nodes)
    if not materialized:
        return ChangeLevel.L2
    level = ChangeLevel.L0
    for node in materialized:
        if node.kind in _L2_KINDS or node.kind not in _L0_KINDS | _L1_KINDS:
            return ChangeLevel.L2
        if node.kind in _L1_KINDS:
            level = ChangeLevel.L1
    return level
