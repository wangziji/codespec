"""Stable process exit codes for the contract delivery CLI."""

from enum import IntEnum


class ExitCode(IntEnum):
    """CLI outcomes defined by the public command contract."""

    SUCCESS = 0
    USAGE = 2
    BLOCKED = 3
    CONFLICT = 4
    FAILED = 5
