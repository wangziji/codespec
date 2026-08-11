"""Version-gated JSON Schema validation for canonical contract records."""

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from .models import Finding

_ADDITIONAL_PROPERTY = re.compile(r"\('(.+)' was unexpected\)")
_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_FORMAT_CHECKER = FormatChecker()
_ENVIRONMENT_ALIASES = frozenset({"ci", "test", "prod"})


@_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Validate the timezone-qualified datetime form required by canonical records."""
    if not isinstance(value, str) or not _RFC3339_DATETIME.fullmatch(value):
        return False
    try:
        normalized = value[:-1] + "+00:00" if value[-1] in "Zz" else value
        return datetime.fromisoformat(normalized[:10] + "T" + normalized[11:]).tzinfo is not None
    except ValueError:
        return False


class SchemaRegistry:
    """Load local schemas and return stable findings instead of raising validation errors."""

    def __init__(self, schema_directory: Path):
        self._schemas = {
            schema_path.name.removesuffix(".schema.json"): json.loads(schema_path.read_text(encoding="utf-8"))
            for schema_path in schema_directory.glob("*.schema.json")
        }

    def validate(self, kind: str, value: object) -> tuple[Finding, ...]:
        """Validate a v1 canonical record, rejecting unknown schema major versions."""
        schema = self._schemas.get(kind)
        if schema is None:
            return (Finding("CDD-SCHEMA-UNKNOWN-KIND", f"Unknown schema kind: {kind}", ""),)
        if not isinstance(value, Mapping):
            return (Finding("CDD-SCHEMA-TYPE", "Contract must be an object.", ""),)

        version = value.get("schema_version")
        if isinstance(version, str) and version.split(".", 1)[0] != "1":
            return (
                Finding(
                    "CDD-SCHEMA-UNKNOWN-MAJOR",
                    f"Unsupported schema major version: {version}",
                    "schema_version",
                ),
            )

        findings = [
            self._finding(error)
            for error in Draft202012Validator(schema, format_checker=_FORMAT_CHECKER).iter_errors(value)
        ]
        if kind == "environment-contract" and not findings:
            findings.extend(self._environment_findings(value))
        return tuple(sorted(findings, key=lambda item: (item.path, item.code, item.message)))

    @staticmethod
    def _environment_findings(value: Mapping[str, object]) -> list[Finding]:
        findings: list[Finding] = []
        for environment in ("ci", "test", "prod"):
            resource = value[environment]
            if not isinstance(resource, Mapping):
                continue
            provider = resource["provider"]
            locator = resource["canonical_locator"]
            if not isinstance(provider, str) or not isinstance(locator, str):
                continue
            try:
                parsed = urlsplit(locator)
                hostname = parsed.hostname or ""
            except ValueError:
                findings.append(
                    Finding(
                        "CDD-ENV-LOCATOR-AUTHORITY",
                        "Canonical locator must have a valid authority host.",
                        f"{environment}.canonical_locator",
                    )
                )
                continue
            path = parsed.path.strip("/")
            locator_path = f"{environment}.canonical_locator"
            if parsed.scheme != provider:
                findings.append(
                    Finding(
                        "CDD-ENV-LOCATOR-SCHEME",
                        "Canonical locator scheme must match provider.",
                        locator_path,
                    )
                )
            elif not hostname:
                findings.append(
                    Finding(
                        "CDD-ENV-LOCATOR-AUTHORITY",
                        "Canonical locator must have a valid authority host.",
                        locator_path,
                    )
                )
            elif not path and not parsed.query:
                findings.append(
                    Finding(
                        "CDD-ENV-LOCATOR-RESOURCE",
                        "Canonical locator must identify a resource path or query.",
                        locator_path,
                    )
                )
            elif SchemaRegistry._is_placeholder_locator(hostname, path, parsed.query):
                findings.append(
                    Finding(
                        "CDD-ENV-LOCATOR-PLACEHOLDER",
                        "Canonical locator must not use an alias or placeholder value.",
                        locator_path,
                    )
                )
        return findings

    @staticmethod
    def _is_placeholder_locator(hostname: str, path: str, query: str) -> bool:
        components = (hostname.lower(), path.lower(), query.lower())
        if any("<" in component or ">" in component for component in components):
            return True
        if any("placeholder" in component or "example" in component for component in components):
            return True
        return hostname.lower() in _ENVIRONMENT_ALIASES or path.lower() in _ENVIRONMENT_ALIASES

    @staticmethod
    def _finding(error: object) -> Finding:
        path = ".".join(str(part) for part in error.absolute_path)
        if error.validator == "required":
            missing = re.search(r"'([^']+)' is a required property", error.message)
            path = ".".join(filter(None, (path, missing.group(1) if missing else "")))
            code = "CDD-SCHEMA-REQUIRED"
        elif error.validator == "additionalProperties":
            unexpected = _ADDITIONAL_PROPERTY.search(error.message)
            path = ".".join(filter(None, (path, unexpected.group(1) if unexpected else "")))
            code = "CDD-SCHEMA-ADDITIONAL-PROPERTY"
        else:
            code = f"CDD-SCHEMA-{str(error.validator).upper()}"
        return Finding(code, error.message, path)
