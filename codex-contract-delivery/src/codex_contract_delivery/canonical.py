"""Safe parsing and deterministic canonical digests for contract records."""

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from pathlib import Path

import yaml


class ContractParseError(ValueError):
    """Raised when a contract is not safe, unambiguous YAML or frontmatter."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of overwriting."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False):
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ContractParseError("contract mapping keys must be strings")
        if key in mapping:
            raise ContractParseError(f"duplicate key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _load_yaml_text(text: str) -> Mapping[str, object]:
    try:
        value = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except ContractParseError:
        raise
    except yaml.YAMLError as error:
        raise ContractParseError(f"safe YAML parsing failed: {error}") from error
    if not isinstance(value, Mapping):
        raise ContractParseError("contract document must contain a mapping")
    return value


def load_yaml(path: Path) -> Mapping[str, object]:
    """Load a YAML mapping without YAML tag execution or duplicate-key ambiguity."""
    return _load_yaml_text(path.read_text(encoding="utf-8"))


def load_markdown_frontmatter(path: Path) -> tuple[Mapping[str, object], str]:
    """Load leading YAML frontmatter and return it separately from Markdown body."""
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ContractParseError("markdown frontmatter must begin with ---")
    closing = normalized.find("\n---\n", 4)
    if closing == -1:
        raise ContractParseError("markdown frontmatter must end with ---")
    return _load_yaml_text(normalized[4:closing]), normalized[closing + 5 :]


def _normalize(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractParseError("contract mapping keys must be strings")
            normalized_key = _normalize(key)
            if normalized_key in normalized:
                raise ContractParseError("normalized mapping key collision")
            normalized[normalized_key] = _normalize(item)
        return normalized
    return value


def canonical_digest(value: object) -> str:
    """Return the SHA-256 digest of canonical Unicode-normalized UTF-8 JSON."""
    payload = json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
