from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from codex_contract_delivery.journal import (
    DatabaseBusy,
    EffectConflict,
    EffectIntent,
    EffectState,
    Journal,
    LeaseHeld,
    ReconciliationRequired,
    RevisionConflict,
    StaleFence,
    TransitionRequest,
)
from codex_contract_delivery.state_machine import InvalidTransition, RunEvent, RunState


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    return tmp_path / "execution.sqlite3"


@pytest.fixture
def journal(journal_path: Path, clock: MutableClock):
    opened = Journal.open(journal_path, clock=clock)
    yield opened
    opened.close()


def request(
    *,
    run_id: str = "run-1",
    expected_revision: int = 0,
    event: RunEvent | str = RunEvent.DISCOVER,
    context: dict[str, object] | None = None,
    effect_id: str | None = None,
) -> TransitionRequest:
    effect = EffectIntent(effect_id, "deployment") if effect_id else None
    return TransitionRequest(run_id, expected_revision, event, context or {}, effect)


def seed_effect(journal: Journal, effect_id: str = "deploy-1") -> None:
    journal.transition(request(effect_id=effect_id))


def test_transition_compare_and_swap_rejects_stale_revision(journal: Journal) -> None:
    """Would fail if a stale caller could append history after another transition won."""
    journal.transition(request(expected_revision=0, event="DISCOVER"))

    with pytest.raises(RevisionConflict):
        journal.transition(request(expected_revision=0, event="DRAFT_REQUIREMENTS"))

    assert journal.get_run("run-1").revision == 1
    assert [event.revision for event in journal.list_events("run-1")] == [1]


def test_transition_rolls_back_state_event_and_effect_together(
    journal: Journal,
) -> None:
    """Would fail if an effect conflict left a partially advanced second run."""
    seed_effect(journal, "globally-unique")

    with pytest.raises(EffectConflict):
        journal.transition(request(run_id="run-2", effect_id="globally-unique"))

    assert journal.get_run("run-2") is None
    assert journal.list_events("run-2") == ()


def test_reopen_preserves_atomic_transition(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if committed state, event, or effect intent were not durable together."""
    first = Journal.open(journal_path, clock=clock)
    result = first.transition(request(effect_id="deploy-1"))
    first.close()

    reopened = Journal.open(journal_path, clock=clock)
    try:
        assert reopened.get_run("run-1") == result.run
        assert reopened.get_effect("run-1", "deploy-1").state is EffectState.INTENT
        assert reopened.list_events("run-1")[0].revision == result.run.revision
    finally:
        reopened.close()


def test_open_is_repeatable_and_enables_sqlite_safety_pragmas(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if reopening changed schema or omitted concurrency/integrity pragmas."""
    first = Journal.open(journal_path, clock=clock)
    second = Journal.open(journal_path, clock=clock)
    assert first._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert first._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5_000
    assert (
        first._connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    )
    assert second._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    first.close()
    second.close()

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"runs", "effects", "leases", "events"} <= tables
    finally:
        connection.close()


def test_takeover_fences_old_worker(journal: Journal, clock: MutableClock) -> None:
    """Would fail if an expired worker retained write authority after takeover."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=0)
    )
    second = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )

    with pytest.raises(StaleFence):
        journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)

    assert second.fence > first.fence
    assert second.dispatch_allowed is True


def test_active_lease_cannot_be_taken_over(journal: Journal) -> None:
    """Would fail if lease ownership could change before its TTL expired."""
    seed_effect(journal)
    journal.acquire_attempt("run-1", "deploy-1", "worker-a", timedelta(minutes=1))

    with pytest.raises(LeaseHeld):
        journal.acquire_attempt("run-1", "deploy-1", "worker-b", timedelta(minutes=1))


def test_expired_current_worker_cannot_record_without_new_fence(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if a worker could write after its lease authority expired."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    clock.advance(timedelta(seconds=2))

    with pytest.raises(StaleFence):
        journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)


def test_completed_evidence_is_immutable_and_identical_replay_is_idempotent(
    journal: Journal,
) -> None:
    """Would fail if completed evidence could be silently rewritten."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    journal.record_effect(
        "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://receipt-1"
    )
    journal.record_effect(
        "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://receipt-1"
    )

    with pytest.raises(EffectConflict):
        journal.record_effect(
            "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://receipt-2"
        )

    assert (
        journal.get_effect("run-1", "deploy-1").evidence_ref == "evidence://receipt-1"
    )


def test_identical_completion_replay_is_idempotent_after_lease_expiry(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if a lost completion acknowledgement became an unsafe retry error."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    journal.record_effect(
        "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://receipt-1"
    )
    clock.advance(timedelta(seconds=2))

    journal.record_effect(
        "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://receipt-1"
    )

    assert journal.get_effect("run-1", "deploy-1").state is EffectState.COMPLETED


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (EffectState.INTENT, EffectState.COMPLETED),
        (EffectState.COMPLETED, EffectState.STARTED),
        (EffectState.RECONCILED, EffectState.COMPLETED),
    ],
)
def test_effect_state_machine_rejects_skipped_or_terminal_transitions(
    journal: Journal, source: EffectState, target: EffectState
) -> None:
    """Would fail if an effect could skip dispatch evidence or leave a terminal state."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    if source is EffectState.COMPLETED:
        journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
        journal.record_effect("deploy-1", lease.fence, source, "evidence://done")
    elif source is EffectState.RECONCILED:
        journal.record_effect("deploy-1", lease.fence, source, "evidence://reconciled")

    with pytest.raises(EffectConflict):
        journal.record_effect("deploy-1", lease.fence, target, "evidence://target")


def test_started_effect_takeover_requires_reconciliation(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if recovery could dispatch an effect whose external outcome is unknown."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    clock.advance(timedelta(seconds=2))

    recovered = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )

    assert recovered.dispatch_allowed is False
    with pytest.raises(ReconciliationRequired):
        recovered.assert_dispatch_allowed()


def test_two_recovery_workers_cannot_both_acquire_dispatch_lease(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if concurrent SQLite connections both believed they won dispatch."""
    seed = Journal.open(journal_path, clock=clock)
    seed_effect(seed)
    seed.close()

    def acquire(worker: str):
        candidate = Journal.open(journal_path, clock=clock)
        try:
            return candidate.acquire_attempt(
                "run-1", "deploy-1", worker, timedelta(minutes=1)
            )
        except LeaseHeld:
            return None
        finally:
            candidate.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = tuple(pool.map(acquire, ("worker-a", "worker-b")))

    winners = [lease for lease in leases if lease is not None]
    assert len(winners) == 1
    assert winners[0].dispatch_allowed is True


def test_locked_database_raises_stable_domain_error(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if callers received unstable sqlite OperationalError details."""
    journal = Journal.open(journal_path, clock=clock, busy_timeout_ms=1)
    blocker = sqlite3.connect(journal_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DatabaseBusy):
            journal.transition(request())
    finally:
        blocker.rollback()
        blocker.close()
        journal.close()


def test_invalid_run_transition_does_not_append_event(journal: Journal) -> None:
    """Would fail if state changed before the lifecycle transition was validated."""
    journal.transition(request())

    with pytest.raises(InvalidTransition):
        journal.transition(request(expected_revision=1, event=RunEvent.ACCEPT))

    assert journal.get_run("run-1").state is RunState.DISCOVERY
    assert len(journal.list_events("run-1")) == 1
