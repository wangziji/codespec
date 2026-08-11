from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from codex_contract_delivery.journal import (
    EffectIntent,
    EffectState,
    Journal,
    LeaseHeld,
    ReconciliationOutcome,
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


class FakeIdempotencyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS receipts (effect_id TEXT PRIMARY KEY)"
        )
        connection.commit()
        connection.close()

    def contains(self, effect_id: str) -> bool:
        connection = sqlite3.connect(self.path)
        try:
            return (
                connection.execute(
                    "SELECT 1 FROM receipts WHERE effect_id = ?", (effect_id,)
                ).fetchone()
                is not None
            )
        finally:
            connection.close()

    def dispatch(self, effect_id: str) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "INSERT OR IGNORE INTO receipts(effect_id) VALUES (?)", (effect_id,)
            )
            connection.commit()
        finally:
            connection.close()

    def count(self, effect_id: str) -> int:
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(
                "SELECT count(*) FROM receipts WHERE effect_id = ?", (effect_id,)
            ).fetchone()[0]
        finally:
            connection.close()


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


def test_crash_after_started_before_call_retries_only_after_observed_absent(
    tmp_path: Path,
) -> None:
    """Would fail if STARTED plus a proven-absent external key became terminal."""
    path = tmp_path / "journal.sqlite3"
    store = FakeIdempotencyStore(tmp_path / "external.sqlite3")
    clock = MutableClock()
    seed_intent(path, clock)

    first = Journal.open(path, clock=clock)
    crashed = first.acquire_attempt(
        "run-1", "publish-release", "worker-a", timedelta(seconds=1)
    )
    first.record_effect("publish-release", crashed.fence, EffectState.STARTED, None)
    first.close()
    clock.advance(timedelta(seconds=2))

    assert store.contains("publish-release") is False
    recovered = Journal.open(path, clock=clock)
    reconcile = recovered.acquire_attempt(
        "run-1", "publish-release", "recovery-a", timedelta(minutes=1)
    )
    assert reconcile.dispatch_allowed is False
    recovered.record_reconciliation(
        "publish-release",
        reconcile.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://external-key-absent",
    )
    retry = recovered.acquire_attempt(
        "run-1", "publish-release", "recovery-a", timedelta(minutes=1)
    )
    retry.assert_dispatch_allowed()
    recovered.record_effect(retry.effect_id, retry.fence, EffectState.STARTED, None)
    store.dispatch(retry.effect_id)
    store.dispatch(retry.effect_id)
    recovered.close()

    assert retry.fence > reconcile.fence
    assert store.count("publish-release") == 1


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
    recovered.record_reconciliation(
        "publish-release",
        new_lease.fence,
        ReconciliationOutcome.OBSERVED_COMPLETED,
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
    recovered.record_reconciliation(
        "publish-release",
        reconcile.fence,
        ReconciliationOutcome.OBSERVED_COMPLETED,
        "evidence://observed-completed-release",
    )

    effect = recovered.get_effect("run-1", "publish-release")
    recovered.close()
    assert reconcile.dispatch_allowed is False
    assert effect.state is EffectState.COMPLETED
    assert effect.evidence_ref == "evidence://observed-completed-release"


def test_two_recovery_workers_cannot_both_acquire_reconciliation_lease(
    tmp_path: Path,
) -> None:
    """Would fail if two probes could both claim recovery authority for STARTED."""
    path = tmp_path / "journal.sqlite3"
    clock = MutableClock()
    seed_intent(path, clock)
    first = Journal.open(path, clock=clock)
    lease = first.acquire_attempt(
        "run-1", "publish-release", "worker-a", timedelta(seconds=1)
    )
    first.record_effect("publish-release", lease.fence, EffectState.STARTED, None)
    first.close()
    clock.advance(timedelta(seconds=2))

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

    winners = [candidate for candidate in leases if candidate is not None]
    assert len(winners) == 1
    assert winners[0].dispatch_allowed is False
