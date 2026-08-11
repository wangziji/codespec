from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_contract_delivery.journal import (
    EffectIntent,
    EffectState,
    Journal,
    LeaseHeld,
    TransitionRequest,
)
from codex_contract_delivery.state_machine import RunEvent


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def seed_intent(path: Path, clock: MutableClock) -> None:
    journal = Journal.open(path, clock=clock)
    journal.transition(
        TransitionRequest(
            "run-1",
            0,
            RunEvent.DISCOVER,
            {},
            EffectIntent("publish-release", "release"),
        )
    )
    journal.close()


def test_crash_before_dispatch_reopens_as_one_dispatchable_attempt(
    tmp_path: Path,
) -> None:
    """Would fail if a durable intent were lost or dispatched by two recovery workers."""
    path = tmp_path / "journal.sqlite3"
    clock = MutableClock()
    seed_intent(path, clock)

    def recover(worker_id: str):
        journal = Journal.open(path, clock=clock)
        try:
            return journal.acquire_attempt(
                "run-1", "publish-release", worker_id, timedelta(minutes=1)
            )
        except LeaseHeld:
            return None
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = tuple(pool.map(recover, ("recovery-a", "recovery-b")))

    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1
    assert winners[0].dispatch_allowed is True


def test_crash_after_external_effect_enters_reconcile_without_duplicate_dispatch(
    tmp_path: Path,
) -> None:
    """Would fail if a started effect were automatically dispatched again after reopen."""
    path = tmp_path / "journal.sqlite3"
    external_receipts = tmp_path / "external-receipts"
    clock = MutableClock()
    seed_intent(path, clock)

    first = Journal.open(path, clock=clock)
    lease = first.acquire_attempt(
        "run-1", "publish-release", "worker-a", timedelta(seconds=1)
    )
    first.record_effect("publish-release", lease.fence, EffectState.STARTED, None)
    external_receipts.write_text("release-created\n", encoding="utf-8")
    clock.advance(timedelta(seconds=2))
    first.close()

    recovered = Journal.open(path, clock=clock)
    new_lease = recovered.acquire_attempt(
        "run-1", "publish-release", "worker-b", timedelta(minutes=1)
    )
    assert new_lease.dispatch_allowed is False
    recovered.record_effect(
        "publish-release",
        new_lease.fence,
        EffectState.RECONCILED,
        "evidence://external-release",
    )
    recovered.close()

    assert external_receipts.read_text(encoding="utf-8").splitlines() == [
        "release-created"
    ]


def test_crash_before_completion_recording_reconciles_same_external_receipt(
    tmp_path: Path,
) -> None:
    """Would fail if recovery overwrote or duplicated an externally completed operation."""
    path = tmp_path / "journal.sqlite3"
    clock = MutableClock()
    seed_intent(path, clock)
    first = Journal.open(path, clock=clock)
    lease = first.acquire_attempt(
        "run-1", "publish-release", "worker-a", timedelta(seconds=1)
    )
    first.record_effect("publish-release", lease.fence, EffectState.STARTED, None)
    clock.advance(timedelta(seconds=2))
    first.close()

    recovered = Journal.open(path, clock=clock)
    reconcile = recovered.acquire_attempt(
        "run-1", "publish-release", "worker-b", timedelta(minutes=1)
    )
    recovered.record_effect(
        "publish-release",
        reconcile.fence,
        EffectState.RECONCILED,
        "evidence://observed-completed-release",
    )

    effect = recovered.get_effect("run-1", "publish-release")
    recovered.close()
    assert reconcile.dispatch_allowed is False
    assert effect.state is EffectState.RECONCILED
    assert effect.evidence_ref == "evidence://observed-completed-release"
