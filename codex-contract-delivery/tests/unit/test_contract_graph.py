from __future__ import annotations

import os
from pathlib import Path

import pytest
from codex_contract_delivery.canonical import canonical_digest, load_yaml
from codex_contract_delivery.contract_graph import (
    ContractGraph,
    ContractResolutionError,
)


def _write_valid_project(root: Path) -> None:
    (root / "contracts").mkdir()
    (root / "deliveries" / "D-001").mkdir(parents=True)
    product = "---\nproduct_id: trade-wise\nrevision: r1\ndigest: " + "p" * 64 + "\n---\n# TradeWise\n\n## R-LOGIN-01\n\nA user can sign in.\n"
    (root / "PRODUCT.md").write_text(product, encoding="utf-8")
    (root / "contracts" / "project-baseline.yaml").write_text(
        "schema_version: '1.0'\nproduct_id: trade-wise\nrevision: base-r1\ndigest: '" + "b" * 64 + "'\n",
        encoding="utf-8",
    )
    product_digest = canonical_digest(
        {"frontmatter": {"product_id": "trade-wise", "revision": "r1", "digest": "p" * 64},
         "body": "# TradeWise\n\n## R-LOGIN-01\n\nA user can sign in.\n"}
    )
    (root / "deliveries" / "D-001" / "contract.yaml").write_text(
        "schema_version: '1.0'\n"
        "delivery_id: D-001\ntype: feature\nbase_revision: base-r1\n"
        "workflow_release_digest: '" + "a" * 64 + "'\n"
        "owner_refs:\n  - kind: product\n    record_id: trade-wise\n    revision: r1\n"
        f"    digest: '{product_digest}'\n    path: PRODUCT.md\n"
        "delta_operations:\n  - id: api-login\n    kind: api\n    action: add\n    value: POST /login\n"
        "cross_layer_impacts: []\nenvironment_obligations: []\nverification: []\ncompletion_conditions: []\n",
        encoding="utf-8",
    )


@pytest.fixture
def valid_project(tmp_path: Path) -> Path:
    _write_valid_project(tmp_path)
    return tmp_path


def test_effective_contract_explains_every_constraint(valid_project: Path) -> None:
    """Would fail if resolved source or delta nodes lost their owning origin."""
    effective = ContractGraph().resolve(valid_project, "D-001")

    assert effective.origin_of("scenario:R-LOGIN-01") == "PRODUCT.md#R-LOGIN-01"
    assert effective.origin_of("delta:api-login") == "deliveries/D-001/contract.yaml"
    assert effective.digest == canonical_digest(effective.nodes)


def test_graph_rejects_conflicting_delta_values(valid_project: Path) -> None:
    """Would fail if a later delta silently won over an incompatible earlier value."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "    value: POST /login\n",
            "    value: POST /login\n  - id: api-login\n    kind: api\n    action: add\n    value: POST /sessions\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-CONFLICT"]


def test_graph_rejects_delivery_based_on_different_baseline(valid_project: Path) -> None:
    """Would fail if a delivery could resolve against a baseline it did not bind."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("base-r1", "base-r0"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-BASELINE-RACE"]


def test_graph_rejects_generated_trace_as_contract_input(valid_project: Path) -> None:
    """Would fail if generated artifacts could alter the resolved contract."""
    generated = valid_project / ".codex-delivery" / "generated"
    generated.mkdir(parents=True)
    (generated / "contract.yaml").write_text("not: an input", encoding="utf-8")

    effective = ContractGraph().resolve(valid_project, "D-001")

    assert effective.origin_of("delta:api-login") == "deliveries/D-001/contract.yaml"


def test_graph_rejects_owner_reference_into_generated_directory(valid_project: Path) -> None:
    """Would fail if a generated artifact could be promoted to an authoritative source."""
    generated = valid_project / ".codex-delivery" / "generated"
    generated.mkdir(parents=True)
    generated_product = generated / "PRODUCT.md"
    generated_product.write_text((valid_project / "PRODUCT.md").read_text(encoding="utf-8"), encoding="utf-8")
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace("path: PRODUCT.md", "path: .codex-delivery/generated/PRODUCT.md"),
        encoding="utf-8",
    )

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-GENERATED-INPUT"]


def test_graph_rejects_child_deletion(valid_project: Path) -> None:
    """Would fail if a delivery could delete a baseline constraint instead of extending it."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("action: add", "action: delete"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-CHILD-WEAKENING"]


def test_trace_connects_declared_scenario_to_delta(valid_project: Path) -> None:
    """Would fail if generated trace output lost a declared scenario-to-delta edge."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    scenario_ref = load_yaml(
        Path(__file__).parents[1] / "fixtures" / "contracts" / "valid" / "scenario-refs.yaml"
    )
    contract.write_text(contract.read_text(encoding="utf-8").replace("    value: POST /login", f"    scenario_refs: {scenario_ref['scenario_refs']}\n    value: POST /login"), encoding="utf-8")

    graph = ContractGraph()
    graph.resolve(valid_project, "D-001")

    assert [(edge.source, edge.target, edge.origin) for edge in graph.trace("R-LOGIN-01")] == [
        ("scenario:R-LOGIN-01", "delta:api-login", "deliveries/D-001/contract.yaml")
    ]


def test_effective_graph_keeps_every_delivery_contract_section(valid_project: Path) -> None:
    """Would fail if graph resolution silently discarded a delivery contract section."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(
        contract.read_text(encoding="utf-8").replace(
            "cross_layer_impacts: []\nenvironment_obligations: []\nverification: []\ncompletion_conditions: []",
            "cross_layer_impacts: [{id: impact-login, kind: ui}]\n"
            "environment_obligations: [{id: env-test, kind: redis}]\n"
            "verification: [{id: verify-login, kind: integration}]\n"
            "completion_conditions: [{id: condition-login, kind: accepted}]",
        ),
        encoding="utf-8",
    )

    effective = ContractGraph().resolve(valid_project, "D-001")

    expected = {
        "product:trade-wise",
        "scenario:R-LOGIN-01",
        "delivery:owner_refs:product:trade-wise",
        "delta:api-login",
        "delivery:cross_layer_impacts:impact-login",
        "delivery:environment_obligations:env-test",
        "delivery:verification:verify-login",
        "delivery:completion_conditions:condition-login",
    }
    assert expected <= set(effective.nodes)
    assert {effective.origin_of(node_id) for node_id in expected} <= {
        "PRODUCT.md",
        "PRODUCT.md#R-LOGIN-01",
        "deliveries/D-001/contract.yaml",
    }


def test_graph_rejects_nested_copied_owner_facts(valid_project: Path) -> None:
    """Would fail if a nested copied goal could bypass source ownership rules."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    copied = load_yaml(
        Path(__file__).parents[1] / "fixtures" / "contracts" / "conflict" / "nested-copied-fact.yaml"
    )
    contract.write_text(contract.read_text(encoding="utf-8").replace("    value: POST /login", f"    details: {copied}\n    value: POST /login"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-COPIED-OWNER-FACT"]


def test_graph_rejects_owner_path_traversal(valid_project: Path, tmp_path: Path) -> None:
    """Would fail if an OwnerRef could escape the declared project root with dot-dot."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "PRODUCT.md").write_text((valid_project / "PRODUCT.md").read_text(encoding="utf-8"), encoding="utf-8")
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("path: PRODUCT.md", "path: ../outside/PRODUCT.md"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-PATH-ESCAPE"]


def test_graph_rejects_delivery_symlink_escape(valid_project: Path, tmp_path: Path) -> None:
    """Would fail if a delivery contract symlink could be read outside the project root."""
    outside = tmp_path.parent / "outside-contract.yaml"
    outside.write_text((valid_project / "deliveries" / "D-001" / "contract.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.unlink()
    os.symlink(outside, contract)

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-PATH-ESCAPE"]


def test_graph_rejects_generated_target_behind_owner_symlink(valid_project: Path) -> None:
    """Would fail if a symlink hid a generated artifact behind a non-generated path."""
    generated = valid_project / ".codex-delivery" / "generated"
    generated.mkdir(parents=True)
    target = generated / "PRODUCT.md"
    target.write_text((valid_project / "PRODUCT.md").read_text(encoding="utf-8"), encoding="utf-8")
    os.symlink(target, valid_project / "linked-product.md")
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("path: PRODUCT.md", "path: linked-product.md"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-GENERATED-INPUT"]


def test_trace_rejects_unknown_scenario_reference(valid_project: Path) -> None:
    """Would fail if a delta could manufacture a trace edge from an unknown scenario."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("    value: POST /login", "    scenario_refs: [R-UNKNOWN]\n    value: POST /login"), encoding="utf-8")

    with pytest.raises(ContractResolutionError) as raised:
        ContractGraph().resolve(valid_project, "D-001")

    assert [finding.code for finding in raised.value.findings] == ["CDD-GRAPH-UNKNOWN-SCENARIO"]


def test_effective_graph_is_deeply_immutable(valid_project: Path) -> None:
    """Would fail if a nested effective node could mutate after its digest was calculated."""
    contract = valid_project / "deliveries" / "D-001" / "contract.yaml"
    contract.write_text(contract.read_text(encoding="utf-8").replace("    value: POST /login", "    details: {nested: [original]}\n    value: POST /login"), encoding="utf-8")

    effective = ContractGraph().resolve(valid_project, "D-001")

    with pytest.raises(TypeError):
        effective.nodes["delta:api-login"]["details"]["nested"][0] = "changed"  # type: ignore[index]
