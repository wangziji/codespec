"""Crash-recoverable SQLite execution journal with fenced effects."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from .approvals import freeze_value
from .state_machine import InvalidTransition, RunEvent, RunState, StateMachine


class JournalError(RuntimeError):
    """Base class for stable journal domain errors."""


class RevisionConflict(JournalError):
    """The expected run revision did not match durable state."""


class EffectConflict(JournalError):
    """An effect identity, state edge, or terminal evidence conflicted."""


class EffectNotFound(JournalError):
    """The requested durable effect intent does not exist."""


class LeaseHeld(JournalError):
    """A different worker owns an unexpired lease."""


class StaleFence(JournalError):
    """A worker attempted to write without the current live fence."""


class ReconciliationRequired(JournalError):
    """The external outcome is unknown and must not be dispatched again."""


class DatabaseBusy(JournalError):
    """SQLite could not begin the bounded write transaction."""


class JournalStorageError(JournalError):
    """SQLite rejected a journal operation for a non-contention reason."""


class EffectState(str, Enum):
    INTENT = "intent"
    STARTED = "started"
    COMPLETED = "completed"
    RECONCILED = "reconciled"


@dataclass(frozen=True)
class EffectIntent:
    effect_id: str
    kind: str

    def __post_init__(self) -> None:
        _require_identifier("effect_id", self.effect_id)
        _require_identifier("kind", self.kind)


@dataclass(frozen=True)
class TransitionRequest:
    run_id: str
    expected_revision: int
    event: RunEvent | str
    context: Mapping[str, object] = field(default_factory=dict)
    effect: EffectIntent | None = None

    def __post_init__(self) -> None:
        _require_identifier("run_id", self.run_id)
        if not isinstance(self.expected_revision, int) or self.expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        if not isinstance(self.context, Mapping):
            raise TypeError("context must be a mapping")
        object.__setattr__(self, "context", freeze_value(self.context))


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    state: RunState
    revision: int
    updated_at: datetime


@dataclass(frozen=True)
class EffectRecord:
    run_id: str
    effect_id: str
    kind: str
    state: EffectState
    evidence_ref: str | None
    updated_at: datetime


@dataclass(frozen=True)
class JournalEvent:
    event_id: int
    run_id: str
    revision: int
    event: RunEvent
    state: RunState
    context: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True)
class TransitionResult:
    run: RunSnapshot
    event: JournalEvent
    effect: EffectRecord | None = None


@dataclass(frozen=True)
class Lease:
    run_id: str
    effect_id: str
    worker_id: str
    fence: int
    expires_at: datetime
    dispatch_allowed: bool

    def assert_dispatch_allowed(self) -> None:
        if not self.dispatch_allowed:
            raise ReconciliationRequired(
                "effect was already started; reconcile its external outcome"
            )


_STATE_VALUES = ", ".join(f"'{state.value}'" for state in RunState)
_EVENT_VALUES = ", ".join(f"'{event.value}'" for event in RunEvent)
_EFFECT_VALUES = ", ".join(f"'{state.value}'" for state in EffectState)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) > 0),
    state TEXT NOT NULL CHECK(state IN ({_STATE_VALUES})),
    revision INTEGER NOT NULL CHECK(revision >= 0),
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS effects (
    run_id TEXT NOT NULL,
    effect_id TEXT NOT NULL UNIQUE CHECK(length(effect_id) > 0),
    kind TEXT NOT NULL CHECK(length(kind) > 0),
    state TEXT NOT NULL CHECK(state IN ({_EFFECT_VALUES})),
    evidence_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, effect_id),
    CHECK (
        (state IN ('intent', 'started') AND evidence_ref IS NULL)
        OR
        (state IN ('completed', 'reconciled') AND length(evidence_ref) > 0)
    ),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS leases (
    run_id TEXT NOT NULL,
    effect_id TEXT NOT NULL,
    worker_id TEXT NOT NULL CHECK(length(worker_id) > 0),
    fence INTEGER NOT NULL CHECK(fence > 0),
    expires_at TEXT NOT NULL,
    PRIMARY KEY (run_id, effect_id),
    FOREIGN KEY (run_id, effect_id) REFERENCES effects(run_id, effect_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    event TEXT NOT NULL CHECK(event IN ({_EVENT_VALUES})),
    state TEXT NOT NULL CHECK(state IN ({_STATE_VALUES})),
    context_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, revision),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER IF NOT EXISTS runs_revision_must_advance
BEFORE UPDATE ON runs
WHEN NEW.revision != OLD.revision + 1
BEGIN
    SELECT RAISE(ABORT, 'run revision must advance by one');
END;

CREATE TRIGGER IF NOT EXISTS leases_fence_must_advance
BEFORE UPDATE ON leases
WHEN NEW.fence <= OLD.fence
BEGIN
    SELECT RAISE(ABORT, 'lease fence must increase');
END;

CREATE TRIGGER IF NOT EXISTS terminal_effects_are_immutable
BEFORE UPDATE ON effects
WHEN OLD.state IN ('completed', 'reconciled')
BEGIN
    SELECT RAISE(ABORT, 'terminal effect is immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_are_immutable_on_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'journal events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_are_immutable_on_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'journal events are immutable');
END;
"""


class Journal:
    """Own one SQLite connection and serialize its local write transactions."""

    def __init__(
        self,
        path: Path,
        connection: sqlite3.Connection,
        clock: Callable[[], datetime],
    ) -> None:
        self.path = path
        self._connection = connection
        self._clock = clock
        self._write_lock = threading.RLock()
        self._machine = StateMachine()

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> Journal:
        path = Path(path)
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(
                path,
                isolation_level=None,
                timeout=busy_timeout_ms / 1_000,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(_SCHEMA)
        except sqlite3.Error as error:
            if "connection" in locals():
                connection.close()
            raise _translate_sqlite(error) from error
        return cls(path, connection, clock or _utc_now)

    def close(self) -> None:
        self._connection.close()

    def transition(self, request: TransitionRequest) -> TransitionResult:
        with self._transaction():
            current = self._connection.execute(
                "SELECT run_id, state, revision, updated_at FROM runs WHERE run_id = ?",
                (request.run_id,),
            ).fetchone()
            if current is None:
                if request.expected_revision != 0:
                    raise RevisionConflict(
                        f"run {request.run_id} does not exist at revision {request.expected_revision}"
                    )
                current_state = RunState.NEW
                current_revision = 0
            else:
                current_state = RunState(current["state"])
                current_revision = current["revision"]
                if current_revision != request.expected_revision:
                    raise RevisionConflict(
                        f"expected revision {request.expected_revision}, found {current_revision}"
                    )

            next_state = self._machine.next_state(
                current_state, request.event, request.context
            )
            try:
                normalized_event = RunEvent(request.event)
            except (TypeError, ValueError) as error:
                raise InvalidTransition("unknown lifecycle event") from error

            if request.effect is not None:
                existing = self._connection.execute(
                    "SELECT run_id FROM effects WHERE effect_id = ?",
                    (request.effect.effect_id,),
                ).fetchone()
                if existing is not None:
                    raise EffectConflict(
                        f"effect_id {request.effect.effect_id} is already owned by run {existing['run_id']}"
                    )

            revision = current_revision + 1
            now = self._now()
            now_text = _format_time(now)
            if current is None:
                self._connection.execute(
                    "INSERT INTO runs(run_id, state, revision, updated_at) VALUES (?, ?, ?, ?)",
                    (request.run_id, next_state.value, revision, now_text),
                )
            else:
                changed = self._connection.execute(
                    "UPDATE runs SET state = ?, revision = ?, updated_at = ? "
                    "WHERE run_id = ? AND revision = ?",
                    (
                        next_state.value,
                        revision,
                        now_text,
                        request.run_id,
                        request.expected_revision,
                    ),
                )
                if changed.rowcount != 1:
                    raise RevisionConflict("run revision changed during transition")

            context_json = json.dumps(
                _json_ready(request.context),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            cursor = self._connection.execute(
                "INSERT INTO events(run_id, revision, event, state, context_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request.run_id,
                    revision,
                    normalized_event.value,
                    next_state.value,
                    context_json,
                    now_text,
                ),
            )
            effect_record = None
            if request.effect is not None:
                self._connection.execute(
                    "INSERT INTO effects(run_id, effect_id, kind, state, evidence_ref, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, NULL, ?, ?)",
                    (
                        request.run_id,
                        request.effect.effect_id,
                        request.effect.kind,
                        EffectState.INTENT.value,
                        now_text,
                        now_text,
                    ),
                )
                effect_record = EffectRecord(
                    request.run_id,
                    request.effect.effect_id,
                    request.effect.kind,
                    EffectState.INTENT,
                    None,
                    now,
                )

            run = RunSnapshot(request.run_id, next_state, revision, now)
            event_record = JournalEvent(
                cursor.lastrowid,
                request.run_id,
                revision,
                normalized_event,
                next_state,
                request.context,
                now,
            )
            return TransitionResult(run, event_record, effect_record)

    def acquire_attempt(
        self,
        run_id: str,
        effect_id: str,
        worker_id: str,
        ttl: timedelta,
    ) -> Lease:
        _require_identifier("run_id", run_id)
        _require_identifier("effect_id", effect_id)
        _require_identifier("worker_id", worker_id)
        if not isinstance(ttl, timedelta) or ttl < timedelta(0):
            raise ValueError("ttl must be a non-negative timedelta")
        with self._transaction():
            effect = self._connection.execute(
                "SELECT state FROM effects WHERE run_id = ? AND effect_id = ?",
                (run_id, effect_id),
            ).fetchone()
            if effect is None:
                raise EffectNotFound(
                    f"effect {effect_id} does not exist for run {run_id}"
                )
            effect_state = EffectState(effect["state"])
            if effect_state in {EffectState.COMPLETED, EffectState.RECONCILED}:
                raise EffectConflict(
                    f"effect {effect_id} is already {effect_state.value}"
                )

            now = self._now()
            current = self._connection.execute(
                "SELECT worker_id, fence, expires_at FROM leases "
                "WHERE run_id = ? AND effect_id = ?",
                (run_id, effect_id),
            ).fetchone()
            if current is not None and _parse_time(current["expires_at"]) > now:
                if current["worker_id"] != worker_id:
                    raise LeaseHeld(
                        f"effect {effect_id} is leased by {current['worker_id']}"
                    )
                return Lease(
                    run_id,
                    effect_id,
                    worker_id,
                    current["fence"],
                    _parse_time(current["expires_at"]),
                    effect_state is EffectState.INTENT,
                )

            fence = 1 if current is None else current["fence"] + 1
            expires_at = now + ttl
            if current is None:
                self._connection.execute(
                    "INSERT INTO leases(run_id, effect_id, worker_id, fence, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_id, effect_id, worker_id, fence, _format_time(expires_at)),
                )
            else:
                self._connection.execute(
                    "UPDATE leases SET worker_id = ?, fence = ?, expires_at = ? "
                    "WHERE run_id = ? AND effect_id = ?",
                    (
                        worker_id,
                        fence,
                        _format_time(expires_at),
                        run_id,
                        effect_id,
                    ),
                )
            return Lease(
                run_id,
                effect_id,
                worker_id,
                fence,
                expires_at,
                effect_state is EffectState.INTENT,
            )

    def record_effect(
        self,
        effect_id: str,
        fence: int,
        state: EffectState,
        evidence_ref: str | None,
    ) -> None:
        _require_identifier("effect_id", effect_id)
        if not isinstance(fence, int) or fence <= 0:
            raise StaleFence("fence must be a positive integer")
        try:
            target = EffectState(state)
        except (TypeError, ValueError) as error:
            raise EffectConflict("unknown effect state") from error
        with self._transaction():
            row = self._connection.execute(
                "SELECT e.run_id, e.state, e.evidence_ref, l.fence, l.expires_at "
                "FROM effects e LEFT JOIN leases l "
                "ON l.run_id = e.run_id AND l.effect_id = e.effect_id "
                "WHERE e.effect_id = ?",
                (effect_id,),
            ).fetchone()
            if row is None:
                raise EffectNotFound(f"effect {effect_id} does not exist")
            current = EffectState(row["state"])
            if (
                current in {EffectState.COMPLETED, EffectState.RECONCILED}
                and current is target
            ):
                if row["evidence_ref"] != evidence_ref:
                    raise EffectConflict(
                        "effect evidence conflicts with durable evidence"
                    )
                return
            if (
                row["fence"] is None
                or row["fence"] != fence
                or _parse_time(row["expires_at"]) <= self._now()
            ):
                raise StaleFence(f"fence {fence} is not current for effect {effect_id}")

            if current is target:
                if row["evidence_ref"] != evidence_ref:
                    raise EffectConflict(
                        "effect evidence conflicts with durable evidence"
                    )
                return

            allowed = {
                EffectState.INTENT: {EffectState.STARTED, EffectState.RECONCILED},
                EffectState.STARTED: {
                    EffectState.COMPLETED,
                    EffectState.RECONCILED,
                },
                EffectState.COMPLETED: set(),
                EffectState.RECONCILED: set(),
            }
            if target not in allowed[current]:
                raise EffectConflict(
                    f"effect cannot transition from {current.value} to {target.value}"
                )
            if target is EffectState.STARTED and evidence_ref is not None:
                raise EffectConflict("started effect cannot carry completion evidence")
            if target in {EffectState.COMPLETED, EffectState.RECONCILED} and (
                not isinstance(evidence_ref, str) or not evidence_ref.strip()
            ):
                raise EffectConflict(f"{target.value} effect requires evidence")

            self._connection.execute(
                "UPDATE effects SET state = ?, evidence_ref = ?, updated_at = ? "
                "WHERE effect_id = ?",
                (target.value, evidence_ref, _format_time(self._now()), effect_id),
            )

    def get_run(self, run_id: str) -> RunSnapshot | None:
        row = self._execute_read(
            "SELECT run_id, state, revision, updated_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunSnapshot(
            row["run_id"],
            RunState(row["state"]),
            row["revision"],
            _parse_time(row["updated_at"]),
        )

    def get_effect(self, run_id: str, effect_id: str) -> EffectRecord | None:
        row = self._execute_read(
            "SELECT run_id, effect_id, kind, state, evidence_ref, updated_at "
            "FROM effects WHERE run_id = ? AND effect_id = ?",
            (run_id, effect_id),
        ).fetchone()
        if row is None:
            return None
        return EffectRecord(
            row["run_id"],
            row["effect_id"],
            row["kind"],
            EffectState(row["state"]),
            row["evidence_ref"],
            _parse_time(row["updated_at"]),
        )

    def list_events(self, run_id: str) -> tuple[JournalEvent, ...]:
        rows = self._execute_read(
            "SELECT event_id, run_id, revision, event, state, context_json, created_at "
            "FROM events WHERE run_id = ? ORDER BY revision",
            (run_id,),
        ).fetchall()
        return tuple(
            JournalEvent(
                row["event_id"],
                row["run_id"],
                row["revision"],
                RunEvent(row["event"]),
                RunState(row["state"]),
                freeze_value(json.loads(row["context_json"])),
                _parse_time(row["created_at"]),
            )
            for row in rows
        )

    def _execute_read(
        self, statement: str, parameters: tuple[object, ...]
    ) -> sqlite3.Cursor:
        try:
            return self._connection.execute(statement, parameters)
        except sqlite3.Error as error:
            raise _translate_sqlite(error) from error

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._write_lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.commit()
            except sqlite3.Error as error:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise _translate_sqlite(error) from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _require_identifier(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _json_ready(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_ready(item) for item in value]
    if isinstance(value, frozenset | set):
        return sorted(_json_ready(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError(f"context value is not JSON serializable: {type(value).__name__}")


def _translate_sqlite(error: sqlite3.Error) -> JournalError:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return DatabaseBusy("journal database is busy")
    return JournalStorageError("journal storage operation failed")
