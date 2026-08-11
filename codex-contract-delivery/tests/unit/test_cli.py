import json
import subprocess
from pathlib import Path

import pytest
from codex_contract_delivery.cli import main

FIXTURE = Path(__file__).parent
SKILL_ROOT = Path(__file__).parents[2]


def test_status_returns_stable_json(capsys):
    """Fail if status stops returning the public uninitialized envelope."""
    exit_code = main(["status", "--root", str(FIXTURE), "--json"])

    body = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert body == {
        "ok": True,
        "command": "status",
        "data": {"phase": "uninitialized"},
        "findings": [],
    }


def test_status_launcher_executes_the_status_subcommand():
    """Fail if the documented status alias is absent or bypasses status."""
    try:
        completed = subprocess.run(
            [str(SKILL_ROOT / "scripts" / "status"), "--json"],
            capture_output=True,
            check=False,
            text=True,
        )
    except FileNotFoundError as error:
        pytest.fail(f"status launcher must be runnable: {error}")

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "ok": True,
        "command": "status",
        "data": {"phase": "uninitialized"},
        "findings": [],
    }
