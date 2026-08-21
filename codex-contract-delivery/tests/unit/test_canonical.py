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


@pytest.mark.parametrize("value", [{1: "integer", "1": "string"}, {"1": "string", 1: "integer"}])
def test_digest_rejects_non_string_mapping_keys_in_any_order(value: object) -> None:
    """Would fail if key stringification silently merged distinct contract fields."""
    with pytest.raises(ContractParseError, match="keys must be strings"):
        canonical_digest(value)


def test_digest_rejects_unicode_normalized_mapping_key_collision() -> None:
    """Would fail if NFC normalization merged two distinct mapping keys."""
    with pytest.raises(ContractParseError, match="normalized mapping key collision"):
        canonical_digest({"cafe\u0301": "decomposed", "caf\u00e9": "composed"})


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


def test_delivery_contract_requires_complete_owner_reference(schema_registry: SchemaRegistry) -> None:
    """Would fail if an owner reference could omit the content digest it binds."""
    value = valid_delivery_contract() | {
        "owner_refs": [
            {"kind": "product", "record_id": "TW", "revision": "r1", "path": "PRODUCT.md"}
        ]
    }

    findings = schema_registry.validate("delivery-contract", value)

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-REQUIRED", "owner_refs.0.digest")
    ]


def test_delivery_contract_rejects_invalid_owner_reference_digest(
    schema_registry: SchemaRegistry,
) -> None:
    """Would fail if owner references accepted non-SHA-256 content identifiers."""
    value = valid_delivery_contract() | {
        "owner_refs": [
            {
                "kind": "product",
                "record_id": "TW",
                "revision": "r1",
                "digest": "not-a-digest",
                "path": "PRODUCT.md",
            }
        ]
    }

    findings = schema_registry.validate("delivery-contract", value)

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-PATTERN", "owner_refs.0.digest")
    ]


def valid_penpot_index() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project": "trade-wise",
        "file": "portfolio",
        "page": "desktop",
        "frame": "overview",
        "scenarios": [],
        "route": "/portfolio",
        "states": [],
        "breakpoints": [],
        "components": [],
        "tokens": [],
    }


@pytest.mark.parametrize(
    "version_field",
    [{"revision": "r42"}, {"snapshot_digest": "c" * 64}],
)
def test_penpot_index_accepts_exactly_one_design_version(
    schema_registry: SchemaRegistry, version_field: dict[str, str]
) -> None:
    """Would fail if either canonical Penpot version pointer branch were unavailable."""
    assert schema_registry.validate("penpot-index", valid_penpot_index() | version_field) == ()


@pytest.mark.parametrize(
    "version_field",
    [{}, {"revision": "r42", "snapshot_digest": "c" * 64}],
)
def test_penpot_index_rejects_missing_or_ambiguous_design_version(
    schema_registry: SchemaRegistry, version_field: dict[str, str]
) -> None:
    """Would fail if a design record had no single authoritative version pointer."""
    findings = schema_registry.validate("penpot-index", valid_penpot_index() | version_field)

    assert [item.code for item in findings] == ["CDD-SCHEMA-ONEOF"]


def valid_environment_contract() -> dict[str, object]:
    def resource(provider: str, locator: str) -> dict[str, object]:
        return {
            "provider": provider,
            "kind": provider,
            "account_or_host": "platform.internal",
            "resource_id": "tradewise-primary",
            "canonical_locator": locator,
            "identity_digest": "sha256:" + "d" * 64,
            "writable": True,
        }

    return {
        "schema_version": "1.0",
        "ci": resource("postgresql", "postgresql://db.internal:5432/tradewise?role=writer"),
        "test": resource("redis", "redis://cache.internal:6379/0"),
        "prod": resource("kubernetes", "kubernetes://cluster.internal/namespace/tradewise?context=prod"),
    }


def test_environment_contract_accepts_structured_writable_resource_identity(
    schema_registry: SchemaRegistry,
) -> None:
    """Would fail if real writable environment identities were no longer supported."""
    assert schema_registry.validate("environment-contract", valid_environment_contract()) == ()


def test_environment_contract_accepts_database_and_non_database_resource(
    schema_registry: SchemaRegistry,
) -> None:
    """Would fail if controlled provider/kind pairs excluded valid V1 resource classes."""
    value = valid_environment_contract()
    value["ci"] = value["ci"] | {
        "provider": "mysql",
        "kind": "mysql",
        "canonical_locator": "mysql://db.internal:3306/tradewise?role=writer",
    }
    value["prod"] = value["prod"] | {
        "provider": "s3",
        "kind": "s3",
        "canonical_locator": "s3://bucket.internal/tradewise-release?region=us-east-1",
    }

    assert schema_registry.validate("environment-contract", value) == ()


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (
            {"provider": "x", "kind": "foo", "canonical_locator": "x://x/foo"},
            "CDD-SCHEMA-ENUM",
        ),
        ({"canonical_locator": "mysql://db.internal:3306/tradewise"}, "CDD-ENV-LOCATOR-SCHEME"),
        ({"canonical_locator": "postgresql:///"}, "CDD-ENV-LOCATOR-AUTHORITY"),
        ({"canonical_locator": "postgresql://prod/prod"}, "CDD-ENV-LOCATOR-PLACEHOLDER"),
        ({"canonical_locator": "postgresql://placeholder.internal/placeholder"}, "CDD-ENV-LOCATOR-PLACEHOLDER"),
        ({"identity_digest": "sha256:not-a-digest"}, "CDD-SCHEMA-PATTERN"),
    ],
)
def test_environment_contract_rejects_unbound_or_placeholder_identity(
    schema_registry: SchemaRegistry, change: dict[str, str], expected_code: str
) -> None:
    """Would fail if untrusted locators or identity probes could look canonical."""
    value = valid_environment_contract()
    value["ci"] = value["ci"] | change

    findings = schema_registry.validate("environment-contract", value)

    assert expected_code in {item.code for item in findings}


@pytest.mark.parametrize("environment", ["ci", "test", "prod"])
def test_environment_contract_rejects_alias_only_resource_identity(
    schema_registry: SchemaRegistry, environment: str
) -> None:
    """Would fail if an environment alias could stand in for a writable resource identity."""
    value = valid_environment_contract()
    value[environment] = value[environment] | {"resource_id": environment}

    findings = schema_registry.validate("environment-contract", value)

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-NOT", f"{environment}.resource_id")
    ]


def test_learning_signal_rejects_malformed_timestamp(schema_registry: SchemaRegistry) -> None:
    """Would fail if JSON Schema date-time annotations remained advisory."""
    findings = schema_registry.validate(
        "learning-signal",
        {
            "schema_version": "1.0",
            "signal_id": "L-1",
            "source": "review",
            "observation": "Malformed timestamps must not enter canonical records.",
            "recorded_at": "not-a-timestamp",
        },
    )

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-FORMAT", "recorded_at")
    ]


def learning_signal(recorded_at: str) -> dict[str, str]:
    return {
        "schema_version": "1.0",
        "signal_id": "L-1",
        "source": "review",
        "observation": "Timestamp validation must follow RFC3339 structure.",
        "recorded_at": recorded_at,
    }


@pytest.mark.parametrize(
    "recorded_at",
    ["2026-08-11T22:00:01Z", "2026-08-11t22:00:01z", "2026-08-11T22:00:01+08:30"],
)
def test_learning_signal_accepts_rfc3339_timestamp_variants(
    schema_registry: SchemaRegistry, recorded_at: str
) -> None:
    """Would fail if valid RFC3339 Z or offset variants were rejected."""
    assert schema_registry.validate("learning-signal", learning_signal(recorded_at)) == ()


@pytest.mark.parametrize(
    "recorded_at",
    [
        "2026-08-11T22:00:01+08:30:15",
        "2026-08-11 22:00:01Z",
        "2026-08-11T22:00:01",
        "2026-08-11T22:00+08:00",
        "2026-02-30T22:00:01Z",
        "2026-08-11T22:00:01+24:00",
    ],
)
def test_learning_signal_rejects_non_rfc3339_timestamp_structure(
    schema_registry: SchemaRegistry, recorded_at: str
) -> None:
    """Would fail if malformed RFC3339 structure or invalid ranges were accepted."""
    findings = schema_registry.validate("learning-signal", learning_signal(recorded_at))

    assert [(item.code, item.path) for item in findings] == [
        ("CDD-SCHEMA-FORMAT", "recorded_at")
    ]


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
