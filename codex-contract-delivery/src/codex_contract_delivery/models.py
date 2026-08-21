"""Immutable value objects used by canonical contract validation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OwnerRef:
    """An immutable pointer to the record that owns a source fact."""

    kind: str
    record_id: str
    revision: str
    digest: str
    path: str


@dataclass(frozen=True)
class Finding:
    """A stable, serializable validation diagnostic."""

    code: str
    message: str
    path: str
