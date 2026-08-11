"""Deterministic, origin-preserving resolution of baseline and delivery contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .approvals import freeze_value
from .canonical import (
    ContractParseError,
    canonical_digest,
    load_markdown_frontmatter,
    load_yaml,
)
from .models import Finding, OwnerRef
from .schema import SchemaRegistry

_SCENARIO_HEADING = re.compile(r"^##\s+(R-[A-Za-z0-9_-]+)\s*$", re.MULTILINE)
_FORBIDDEN_DELTA_KEYS = frozenset(
    {"goal", "goals", "scenario", "scenarios", "api", "apis", "api_definition", "api_definitions", "data_definition", "data_definitions", "data_model", "data_models"}
)
_DELIVERY_SECTIONS = (
    "cross_layer_impacts",
    "environment_obligations",
    "verification",
    "completion_conditions",
)


class ContractResolutionError(ValueError):
    """Raised with stable findings when a contract graph cannot be resolved."""

    def __init__(self, findings: tuple[Finding, ...]):
        self.findings = findings
        super().__init__("; ".join(finding.code for finding in findings))


@dataclass(frozen=True)
class TraceEdge:
    source: str
    target: str
    origin: str


@dataclass(frozen=True)
class EffectiveContract:
    nodes: Mapping[str, Mapping[str, object]]
    origins: Mapping[str, str]
    digest: str

    def origin_of(self, node_id: str) -> str:
        return self.origins[node_id]


class ContractGraph:
    """Resolve one baseline and one delivery delta; no inherited overwrite semantics."""

    def __init__(self, schema_registry: SchemaRegistry | None = None):
        self._schema_registry = schema_registry
        self._traces: dict[str, tuple[TraceEdge, ...]] = {}

    def resolve(self, project_root: Path, delivery_id: str) -> EffectiveContract:
        root = project_root.resolve()
        registry = self._schema_registry or SchemaRegistry(Path(__file__).parents[2] / "schemas")
        baseline_path, baseline = self._find_baseline(root, registry)
        delivery_path = self._safe_input_path(root, root / "deliveries" / delivery_id / "contract.yaml")
        try:
            delivery = load_yaml(delivery_path)
        except (OSError, ContractParseError) as error:
            raise ContractResolutionError((Finding("CDD-GRAPH-DELIVERY-LOAD", str(error), str(delivery_path)),)) from error
        findings = registry.validate("delivery-contract", delivery)
        if findings:
            raise ContractResolutionError(findings)
        if delivery.get("delivery_id") != delivery_id:
            raise ContractResolutionError((Finding("CDD-GRAPH-DELIVERY-ID", "Delivery id does not match path.", "delivery_id"),))
        if delivery.get("base_revision") != baseline.get("revision"):
            raise ContractResolutionError((Finding("CDD-GRAPH-BASELINE-RACE", "Delivery base revision does not match the project baseline.", "base_revision"),))

        nodes: dict[str, Mapping[str, object]] = {}
        origins: dict[str, str] = {}
        baseline_id = f"baseline:{baseline['product_id']}"
        nodes[baseline_id] = freeze_value(baseline)
        origins[baseline_id] = self._relative(root, baseline_path)
        for owner in self._owner_refs(delivery):
            self._add_owner_nodes(root, owner, nodes, origins)
            owner_id = f"delivery:owner_refs:{owner.kind}:{owner.record_id}"
            self._add_node(nodes, origins, owner_id, owner.__dict__, self._relative(root, delivery_path))
        self._add_delta_nodes(delivery, root, delivery_path, nodes, origins)
        for section in _DELIVERY_SECTIONS:
            self._add_delivery_section(delivery, section, root, delivery_path, nodes, origins)
        frozen_nodes = freeze_value(nodes)
        effective = EffectiveContract(
            frozen_nodes,
            freeze_value(origins),
            canonical_digest(frozen_nodes),
        )
        self._traces = self._build_traces(delivery, root, delivery_path, frozenset(nodes))
        return effective

    def trace(self, scenario_id: str) -> tuple[TraceEdge, ...]:
        """Return only generated trace edges from the last successful resolution."""
        return self._traces.get(scenario_id, ())

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return path.relative_to(root).as_posix()

    @staticmethod
    def _safe_input_path(root: Path, candidate: Path) -> Path:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ContractResolutionError((Finding("CDD-GRAPH-PATH-ESCAPE", "Contract input escapes the project root.", str(candidate)),))
        return resolved

    @staticmethod
    def _is_generated(root: Path, path: Path) -> bool:
        return ".codex-delivery/generated" in path.relative_to(root).as_posix()

    def _find_baseline(self, root: Path, registry: SchemaRegistry) -> tuple[Path, Mapping[str, object]]:
        candidates: list[tuple[Path, Mapping[str, object]]] = []
        for path in root.rglob("*.yaml"):
            path = self._safe_input_path(root, path)
            if self._is_generated(root, path):
                continue
            try:
                value = load_yaml(path)
            except (OSError, ContractParseError):
                continue
            if registry.validate("project-baseline", value) == ():
                candidates.append((path, value))
        if len(candidates) != 1:
            raise ContractResolutionError((Finding("CDD-GRAPH-BASELINE-COUNT", "Exactly one project baseline is required.", ""),))
        return candidates[0]

    @staticmethod
    def _owner_refs(delivery: Mapping[str, object]) -> tuple[OwnerRef, ...]:
        raw_refs = delivery["owner_refs"]
        assert isinstance(raw_refs, list)
        return tuple(OwnerRef(**raw) for raw in raw_refs if isinstance(raw, Mapping))

    def _add_owner_nodes(
        self,
        root: Path,
        owner: OwnerRef,
        nodes: dict[str, Mapping[str, object]],
        origins: dict[str, str],
    ) -> None:
        path = self._safe_input_path(root, root / owner.path)
        if self._is_generated(root, path):
            raise ContractResolutionError((Finding("CDD-GRAPH-GENERATED-INPUT", "Generated artifacts cannot be authoritative contract inputs.", owner.path),))
        if owner.kind != "product" or path.name != "PRODUCT.md":
            raise ContractResolutionError((Finding("CDD-GRAPH-OWNER-UNSUPPORTED", "Unsupported owner reference.", owner.path),))
        try:
            metadata, body = load_markdown_frontmatter(path)
        except (OSError, ContractParseError) as error:
            raise ContractResolutionError((Finding("CDD-GRAPH-OWNER-LOAD", str(error), owner.path),)) from error
        actual = canonical_digest({"frontmatter": metadata, "body": body})
        if metadata.get("product_id") != owner.record_id or metadata.get("revision") != owner.revision or actual != owner.digest:
            raise ContractResolutionError((Finding("CDD-GRAPH-OWNER-MISMATCH", "Owner reference does not bind the authoritative product record.", owner.path),))
        product_id = f"product:{owner.record_id}"
        self._add_node(nodes, origins, product_id, {"frontmatter": metadata, "body": body}, owner.path)
        for match in _SCENARIO_HEADING.finditer(body):
            scenario_id = match.group(1)
            node_id = f"scenario:{scenario_id}"
            self._add_node(nodes, origins, node_id, {"kind": "scenario", "id": scenario_id}, f"{owner.path}#{scenario_id}")

    def _add_delta_nodes(
        self,
        delivery: Mapping[str, object],
        root: Path,
        delivery_path: Path,
        nodes: dict[str, Mapping[str, object]],
        origins: dict[str, str],
    ) -> None:
        operations = delivery["delta_operations"]
        assert isinstance(operations, list)
        origin = self._relative(root, delivery_path)
        for operation in operations:
            if not isinstance(operation, Mapping) or not isinstance(operation.get("id"), str) or not isinstance(operation.get("kind"), str):
                raise ContractResolutionError((Finding("CDD-GRAPH-INVALID-DELTA", "Delta must have string id and kind.", "delta_operations"),))
            action = operation.get("action", "add")
            if action in {"delete", "remove", "weaken"}:
                raise ContractResolutionError((Finding("CDD-GRAPH-CHILD-WEAKENING", "Delivery deltas cannot weaken or delete baseline constraints.", f"delta_operations.{operation['id']}"),))
            if action != "add":
                raise ContractResolutionError((Finding("CDD-GRAPH-INVALID-DELTA", "Only additive delivery deltas are supported.", f"delta_operations.{operation['id']}"),))
            if self._contains_forbidden_owner_fact(operation):
                raise ContractResolutionError((Finding("CDD-GRAPH-COPIED-OWNER-FACT", "Delta contains copied owner facts.", f"delta_operations.{operation['id']}"),))
            self._add_node(nodes, origins, f"delta:{operation['id']}", operation, origin)

    def _add_delivery_section(
        self,
        delivery: Mapping[str, object],
        section: str,
        root: Path,
        delivery_path: Path,
        nodes: dict[str, Mapping[str, object]],
        origins: dict[str, str],
    ) -> None:
        items = delivery[section]
        if not isinstance(items, list):
            raise ContractResolutionError((Finding("CDD-GRAPH-UNEXPLAINABLE-PAYLOAD", "Delivery section must be a list.", section),))
        origin = self._relative(root, delivery_path)
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ContractResolutionError((Finding("CDD-GRAPH-UNEXPLAINABLE-PAYLOAD", "Delivery items require a stable string id.", section),))
            self._add_node(nodes, origins, f"delivery:{section}:{item['id']}", item, origin)

    @staticmethod
    def _contains_forbidden_owner_fact(value: object) -> bool:
        if isinstance(value, Mapping):
            return any(
                str(key).lower().replace("-", "_") in _FORBIDDEN_DELTA_KEYS
                or ContractGraph._contains_forbidden_owner_fact(item)
                for key, item in value.items()
            )
        if isinstance(value, list | tuple):
            return any(ContractGraph._contains_forbidden_owner_fact(item) for item in value)
        return False

    @staticmethod
    def _add_node(
        nodes: dict[str, Mapping[str, object]], origins: dict[str, str], node_id: str, value: object, origin: str
    ) -> None:
        frozen = freeze_value(value)
        if not isinstance(frozen, Mapping):
            raise ContractResolutionError((Finding("CDD-GRAPH-UNEXPLAINABLE-PAYLOAD", "Effective nodes must be mappings.", node_id),))
        if node_id in nodes and nodes[node_id] != frozen:
            raise ContractResolutionError((Finding("CDD-GRAPH-CONFLICT", "Conflicting values for the same effective node.", node_id),))
        nodes[node_id] = frozen
        origins[node_id] = origin

    def _build_traces(self, delivery: Mapping[str, object], root: Path, delivery_path: Path, node_ids: frozenset[str]) -> dict[str, tuple[TraceEdge, ...]]:
        traces: dict[str, list[TraceEdge]] = {}
        operations = delivery["delta_operations"]
        assert isinstance(operations, list)
        origin = self._relative(root, delivery_path)
        for operation in operations:
            if not isinstance(operation, Mapping):
                continue
            scenarios = operation.get("scenario_refs", ())
            if not isinstance(scenarios, list) or not isinstance(operation.get("id"), str):
                continue
            for scenario_id in scenarios:
                if isinstance(scenario_id, str):
                    if f"scenario:{scenario_id}" not in node_ids:
                        raise ContractResolutionError((Finding("CDD-GRAPH-UNKNOWN-SCENARIO", "Trace references an unknown scenario.", scenario_id),))
                    traces.setdefault(scenario_id, []).append(TraceEdge(f"scenario:{scenario_id}", f"delta:{operation['id']}", origin))
        return {key: tuple(value) for key, value in traces.items()}
