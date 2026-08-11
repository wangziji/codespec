from __future__ import annotations

from pathlib import Path

import pytest
from codex_contract_delivery.canonical import canonical_digest
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
    contract.write_text(contract.read_text(encoding="utf-8").replace("    value: POST /login", "    scenarios: [R-LOGIN-01]\n    value: POST /login"), encoding="utf-8")

    graph = ContractGraph()
    graph.resolve(valid_project, "D-001")

    assert [(edge.source, edge.target, edge.origin) for edge in graph.trace("R-LOGIN-01")] == [
        ("scenario:R-LOGIN-01", "delta:api-login", "deliveries/D-001/contract.yaml")
    ]
