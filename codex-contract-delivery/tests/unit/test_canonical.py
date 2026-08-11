from __future__ import annotations

from pathlib import Path

import pytest
from codex_contract_delivery.canonical import (
    ContractParseError,
    canonical_digest,
    load_markdown_frontmatter,
    load_yaml,
)
from codex_contract_delivery.models import OwnerRef
from codex_contract_delivery.schema import SchemaRegistry


def valid_delivery_contract() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "delivery_id": "CDD-12",
        "type": "feature",
        "base_revision": "aa49549",
        "workflow_release_digest": "a" * 64,
        "owner_refs": [],
        "delta_operations": [],
        "cross_layer_impacts": [],
        "environment_obligations": [],
        "verification": [],
        "completion_conditions": [],
    }


@pytest.fixture
def schema_registry() -> SchemaRegistry:
    return SchemaRegistry(Path(__file__).parents[2] / "schemas")


def test_yaml_key_order_does_not_change_digest() -> None:
    """Would fail if digest depended on mapping insertion order."""
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


def test_digest_normalizes_unicode_and_line_endings() -> None:
    """Would fail if equivalent Unicode or CRLF payloads hashed differently."""
    assert canonical_digest({"note": "cafe\u0301\r\nnext"}) == canonical_digest(
        {"note": "caf\u00e9\nnext"}
    )


def test_yaml_loader_rejects_duplicate_mapping_keys(tmp_path: Path) -> None:
    """Would fail if a later duplicate key silently changed contract meaning."""
    contract = tmp_path / "duplicate.yaml"
    contract.write_text("delivery_id: first\ndelivery_id: second\n", encoding="utf-8")

    with pytest.raises(ContractParseError, match="duplicate key"):
        load_yaml(contract)


def test_yaml_loader_rejects_non_string_mapping_keys(tmp_path: Path) -> None:
    """Would fail if malformed YAML keys escaped the contract parse boundary."""
    contract = tmp_path / "non-string-key.yaml"
    contract.write_text("? [not, a, string]\n: value\n", encoding="utf-8")

    with pytest.raises(ContractParseError, match="keys must be strings"):
        load_yaml(contract)


def test_yaml_loader_rejects_executable_tags(tmp_path: Path) -> None:
    """Would fail if YAML constructors could execute or construct tagged values."""
    contract = tmp_path / "unsafe.yaml"
    contract.write_text("value: !!python/object/apply:os.system ['echo unsafe']\n", encoding="utf-8")

    with pytest.raises(ContractParseError, match="safe YAML"):
        load_yaml(contract)


def test_markdown_frontmatter_returns_metadata_and_body(tmp_path: Path) -> None:
    """Would fail if markdown ownership metadata were not parsed as safe YAML."""
    document = tmp_path / "PRODUCT.md"
    document.write_text("---\nproduct_id: trade-wise\n---\n# Product\n", encoding="utf-8")

    metadata, body = load_markdown_frontmatter(document)

    assert metadata == {"product_id": "trade-wise"}
    assert body == "# Product\n"


def test_delivery_contract_rejects_copied_goal(schema_registry: SchemaRegistry) -> None:
    """Would fail if delivery contracts could duplicate product-goal ownership."""
    value = valid_delivery_contract() | {"goals": [{"id": "G-1", "text": "copied"}]}

    findings = schema_registry.validate("delivery-contract", value)

    assert [item.code for item in findings] == ["CDD-SCHEMA-ADDITIONAL-PROPERTY"]
    assert findings[0].path == "goals"


def test_module_requires_business_boundary_and_owner(schema_registry: SchemaRegistry) -> None:
    """Would fail if modules omitted independently owned boundaries."""
    findings = schema_registry.validate("architecture-module", {"module_id": "portfolio"})

    assert {item.path for item in findings} >= {
        "business_capability",
        "data_owners",
        "interfaces",
        "submodules",
    }


def test_registry_rejects_unknown_schema_major(schema_registry: SchemaRegistry) -> None:
    """Would fail if a v2 contract were accepted by v1 validation rules."""
    findings = schema_registry.validate(
        "delivery-contract", valid_delivery_contract() | {"schema_version": "2.0"}
    )

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-UNKNOWN-MAJOR", "schema_version")
    ]


def test_owner_reference_is_immutable() -> None:
    """Would fail if a loaded ownership reference could be changed in place."""
    owner = OwnerRef("product", "TW", "r1", "b" * 64, "PRODUCT.md")

    with pytest.raises(AttributeError):
        owner.record_id = "other"  # type: ignore[misc]
