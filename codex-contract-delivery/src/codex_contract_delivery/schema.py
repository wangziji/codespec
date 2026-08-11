"""Version-gated JSON Schema validation for canonical contract records."""

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .models import Finding

_ADDITIONAL_PROPERTY = re.compile(r"\('(.+)' was unexpected\)")
_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Validate the timezone-qualified datetime form required by canonical records."""
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
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
        return tuple(sorted(findings, key=lambda item: (item.path, item.code, item.message)))

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
