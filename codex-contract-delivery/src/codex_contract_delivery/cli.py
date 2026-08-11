"""Command shell for Codex contract delivery."""

import argparse
import json
from collections.abc import Sequence

from .errors import ExitCode

COMMANDS = (
    "init",
    "doctor",
    "status",
    "validate",
    "trace",
    "next",
    "budget",
    "evidence",
    "learn",
    "evaluate",
    "promote",
    "rollback",
)


def build_parser(commands: Sequence[str] = COMMANDS) -> argparse.ArgumentParser:
    """Build the stable command surface, including pending subcommands."""
    parser = argparse.ArgumentParser(prog="cdd")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in commands:
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--root", default=".")
        subparser.add_argument("--json", action="store_true")
    return parser


def emit(command: str, ok: bool, data: object, findings: list[object]) -> None:
    """Write the version-one JSON command envelope."""
    print(json.dumps({"ok": ok, "command": command, "data": data, "findings": findings}))


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch implemented behavior and report unavailable commands honestly."""
    if args.command == "status":
        emit("status", True, {"phase": "uninitialized"}, [])
        return ExitCode.SUCCESS

    emit(
        args.command,
        False,
        {"status": "not_implemented"},
        [{"code": "blocked/not_implemented", "message": "Command is not implemented yet."}],
    )
    return ExitCode.BLOCKED


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command shell and return its stable process status."""
    parser = build_parser(COMMANDS)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return ExitCode.USAGE if error.code else ExitCode.SUCCESS
    return dispatch(args)
