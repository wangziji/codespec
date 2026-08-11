import json
from pathlib import Path

from codex_contract_delivery.cli import main

FIXTURE = Path(__file__).parent


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
