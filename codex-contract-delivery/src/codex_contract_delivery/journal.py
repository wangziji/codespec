"""Crash-recoverable SQLite execution journal with fenced effects."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


class ClockRollback(JournalError):
    """The observed wall clock moved behind durable lease time."""


class JournalStorageError(JournalError):
    """SQLite rejected a journal operation for a non-contention reason."""


class EffectState(str, Enum):
    INTENT = "intent"
    STARTED = "started"
    PREPARED = "prepared"
    COMPLETED = "completed"
    RECONCILED = "reconciled"


class ReconciliationOutcome(str, Enum):
    OBSERVED_COMPLETED = "observed_completed"
    OBSERVED_ABSENT = "observed_absent"
    UNKNOWN = "unknown"


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
class ReconciliationRecord:
    reconciliation_id: int
    run_id: str
    effect_id: str
    fence: int
    outcome: ReconciliationOutcome
    evidence_ref: str
    observed_at: datetime


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
_RECONCILIATION_VALUES = ", ".join(
    f"'{outcome.value}'" for outcome in ReconciliationOutcome
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS journal_metadata (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
    last_observed_time TEXT
) STRICT;

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
        (state IN ('intent', 'started', 'reconciled') AND evidence_ref IS NULL)
        OR
        (state IN ('prepared', 'completed') AND length(evidence_ref) > 0)
    ),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS reconciliations (
    reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    effect_id TEXT NOT NULL,
    fence INTEGER NOT NULL CHECK(fence > 0),
    outcome TEXT NOT NULL CHECK(outcome IN ({_RECONCILIATION_VALUES})),
    evidence_ref TEXT NOT NULL CHECK(length(evidence_ref) > 0),
    observed_at TEXT NOT NULL,
    UNIQUE (effect_id, fence),
    FOREIGN KEY (run_id, effect_id) REFERENCES effects(run_id, effect_id)
        ON DELETE RESTRICT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_effects_run_state
ON effects(run_id, state);

CREATE INDEX IF NOT EXISTS idx_reconciliations_effect
ON reconciliations(effect_id, reconciliation_id);

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
WHEN NEW.fence != OLD.fence AND NEW.fence <= OLD.fence
BEGIN
    SELECT RAISE(ABORT, 'lease fence must increase');
END;

CREATE TRIGGER IF NOT EXISTS terminal_effects_are_immutable
BEFORE UPDATE ON effects
WHEN OLD.state = 'completed'
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

CREATE TRIGGER IF NOT EXISTS reconciliations_are_immutable_on_update
BEFORE UPDATE ON reconciliations
BEGIN
    SELECT RAISE(ABORT, 'reconciliation audit is immutable');
END;

CREATE TRIGGER IF NOT EXISTS reconciliations_are_immutable_on_delete
BEFORE DELETE ON reconciliations
BEGIN
    SELECT RAISE(ABORT, 'reconciliation audit is immutable');
END;

INSERT INTO journal_metadata(singleton, schema_version, last_observed_time)
VALUES (1, 3, NULL);
"""


def _sql_statements(script: str) -> tuple[str, ...]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines():
        pending += line + "\n"
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                statements.append(statement)
            pending = ""
    if pending.strip():
        raise RuntimeError("internal schema contains an incomplete SQL statement")
    return tuple(statements)


def _normalize_schema_sql(statement: str) -> str:
    normalized = re.sub(r"\bif\s+not\s+exists\b", "", statement, flags=re.IGNORECASE)
    return " ".join(normalized.lower().strip().removesuffix(";").split())


def _sql_manifest(
    statements: tuple[str, ...],
) -> dict[tuple[str, str], str]:
    manifest: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"^create\s+(table|index|trigger)\s+(?:if\s+not\s+exists\s+)?([^\s(]+)",
        re.IGNORECASE,
    )
    for statement in statements:
        match = pattern.match(statement.strip())
        if match is not None:
            manifest[(match.group(1).lower(), match.group(2).strip('"').lower())] = (
                _normalize_schema_sql(statement)
            )
    return manifest


_CURRENT_SCHEMA_VERSION = 3
_CURRENT_SCHEMA_STATEMENTS = _sql_statements(_SCHEMA)
_CURRENT_SQL_MANIFEST = _sql_manifest(_CURRENT_SCHEMA_STATEMENTS)
_V2_SCHEMA = (
    _SCHEMA.replace(", 'prepared'", "")
    .replace(
        "(state IN ('intent', 'started', 'reconciled') AND evidence_ref IS NULL)\n"
        "        OR\n"
        "        (state IN ('prepared', 'completed') AND length(evidence_ref) > 0)",
        "(state IN ('intent', 'started', 'reconciled') AND evidence_ref IS NULL)\n"
        "        OR\n"
        "        (state = 'completed' AND length(evidence_ref) > 0)",
    )
    .replace("VALUES (1, 3, NULL);", "VALUES (1, 2, NULL);")
)
_V2_SCHEMA_STATEMENTS = _sql_statements(_V2_SCHEMA)
_V2_SQL_MANIFEST = _sql_manifest(_V2_SCHEMA_STATEMENTS)
# Commits 43a520d and 6618ed0 published the same v1 DDL; it differs from v2
# only in reconciliation uniqueness and the metadata seed version.
_V1_SCHEMA = _V2_SCHEMA.replace(
    "UNIQUE (effect_id, fence),",
    "UNIQUE (effect_id, fence, outcome, evidence_ref),",
).replace("VALUES (1, 2, NULL);", "VALUES (1, 1, NULL);")
_V1_SCHEMA_STATEMENTS = _sql_statements(_V1_SCHEMA)
_V1_SQL_MANIFEST = _sql_manifest(_V1_SCHEMA_STATEMENTS)

_BA17_EFFECTS_SQL = """
CREATE TABLE effects (
    run_id TEXT NOT NULL,
    effect_id TEXT NOT NULL UNIQUE CHECK(length(effect_id) > 0),
    kind TEXT NOT NULL CHECK(length(kind) > 0),
    state TEXT NOT NULL CHECK(state IN ('intent', 'started', 'completed', 'reconciled')),
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
) STRICT
"""
_BA17_LEASE_TRIGGER_SQL = """
CREATE TRIGGER leases_fence_must_advance
BEFORE UPDATE ON leases
WHEN NEW.fence <= OLD.fence
BEGIN SELECT RAISE(ABORT, 'lease fence must increase'); END
"""
_BA17_TERMINAL_TRIGGER_SQL = """
CREATE TRIGGER terminal_effects_are_immutable
BEFORE UPDATE ON effects
WHEN OLD.state IN ('completed', 'reconciled')
BEGIN SELECT RAISE(ABORT, 'terminal effect is immutable'); END
"""
_BA17_OBJECT_KEYS = frozenset(
    {
        ("table", "runs"),
        ("table", "effects"),
        ("table", "leases"),
        ("table", "events"),
        ("trigger", "runs_revision_must_advance"),
        ("trigger", "leases_fence_must_advance"),
        ("trigger", "terminal_effects_are_immutable"),
        ("trigger", "events_are_immutable_on_update"),
        ("trigger", "events_are_immutable_on_delete"),
    }
)
_BA17_SQL_MANIFEST = {
    key: value for key, value in _V1_SQL_MANIFEST.items() if key in _BA17_OBJECT_KEYS
}
_BA17_SQL_MANIFEST[("table", "effects")] = _normalize_schema_sql(_BA17_EFFECTS_SQL)
_BA17_SQL_MANIFEST[("trigger", "leases_fence_must_advance")] = _normalize_schema_sql(
    _BA17_LEASE_TRIGGER_SQL
)
_BA17_SQL_MANIFEST[("trigger", "terminal_effects_are_immutable")] = (
    _normalize_schema_sql(_BA17_TERMINAL_TRIGGER_SQL)
)

_BA17_TO_V1_STATEMENTS = (
    "DROP TRIGGER runs_revision_must_advance",
    "DROP TRIGGER leases_fence_must_advance",
    "DROP TRIGGER terminal_effects_are_immutable",
    "DROP TRIGGER events_are_immutable_on_update",
    "DROP TRIGGER events_are_immutable_on_delete",
    "ALTER TABLE leases RENAME TO leases_ba17dca",
    "ALTER TABLE effects RENAME TO effects_ba17dca",
    *_V1_SCHEMA_STATEMENTS,
    """INSERT INTO effects(
        run_id, effect_id, kind, state, evidence_ref, created_at, updated_at
    )
    SELECT run_id, effect_id, kind, state,
           CASE WHEN state = 'reconciled' THEN NULL ELSE evidence_ref END,
           created_at, updated_at
    FROM effects_ba17dca""",
    """INSERT INTO reconciliations(
        run_id, effect_id, fence, outcome, evidence_ref, observed_at
    )
    SELECT e.run_id, e.effect_id, 0, 'unknown', e.evidence_ref, e.updated_at
    FROM effects_ba17dca e
    LEFT JOIN leases_ba17dca l
      ON l.run_id = e.run_id AND l.effect_id = e.effect_id
    WHERE e.state = 'reconciled' AND l.effect_id IS NULL""",
    """INSERT INTO leases(run_id, effect_id, worker_id, fence, expires_at)
    SELECT run_id, effect_id, worker_id, fence, expires_at
    FROM leases_ba17dca""",
    """INSERT INTO reconciliations(
        run_id, effect_id, fence, outcome, evidence_ref, observed_at
    )
    SELECT e.run_id, e.effect_id, l.fence, 'unknown', e.evidence_ref, e.updated_at
    FROM effects_ba17dca e
    JOIN leases_ba17dca l
      ON l.run_id = e.run_id AND l.effect_id = e.effect_id
    WHERE e.state = 'reconciled'""",
    "DROP TABLE leases_ba17dca",
    "DROP TABLE effects_ba17dca",
)


def _object_statement(statements: tuple[str, ...], kind: str, name: str) -> str:
    expected = (kind, name)
    for statement in statements:
        if expected in _sql_manifest((statement,)):
            return statement
    raise RuntimeError(f"internal schema object {kind} {name} is missing")


_V1_TO_V2_STATEMENTS = (
    "DROP TRIGGER reconciliations_are_immutable_on_update",
    "DROP TRIGGER reconciliations_are_immutable_on_delete",
    "DROP INDEX idx_reconciliations_effect",
    "ALTER TABLE reconciliations RENAME TO reconciliations_v1",
    _object_statement(_CURRENT_SCHEMA_STATEMENTS, "table", "reconciliations"),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS, "index", "idx_reconciliations_effect"
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS,
        "trigger",
        "reconciliations_are_immutable_on_update",
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS,
        "trigger",
        "reconciliations_are_immutable_on_delete",
    ),
    """INSERT INTO reconciliations(
        reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at
    )
    SELECT reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at
    FROM reconciliations_v1 ORDER BY reconciliation_id""",
    "DROP TABLE reconciliations_v1",
)
_V2_TO_V3_STATEMENTS = (
    "DROP TRIGGER terminal_effects_are_immutable",
    "DROP TRIGGER leases_fence_must_advance",
    "DROP TRIGGER reconciliations_are_immutable_on_update",
    "DROP TRIGGER reconciliations_are_immutable_on_delete",
    "DROP INDEX idx_effects_run_state",
    "DROP INDEX idx_reconciliations_effect",
    "ALTER TABLE leases RENAME TO leases_v2",
    "ALTER TABLE reconciliations RENAME TO reconciliations_v2",
    "ALTER TABLE effects RENAME TO effects_v2",
    _object_statement(_CURRENT_SCHEMA_STATEMENTS, "table", "effects"),
    _object_statement(_CURRENT_SCHEMA_STATEMENTS, "table", "reconciliations"),
    _object_statement(_CURRENT_SCHEMA_STATEMENTS, "table", "leases"),
    _object_statement(_CURRENT_SCHEMA_STATEMENTS, "index", "idx_effects_run_state"),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS, "index", "idx_reconciliations_effect"
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS, "trigger", "terminal_effects_are_immutable"
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS, "trigger", "leases_fence_must_advance"
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS,
        "trigger",
        "reconciliations_are_immutable_on_update",
    ),
    _object_statement(
        _CURRENT_SCHEMA_STATEMENTS,
        "trigger",
        "reconciliations_are_immutable_on_delete",
    ),
    """INSERT INTO effects(
        run_id, effect_id, kind, state, evidence_ref, created_at, updated_at
    )
    SELECT run_id, effect_id, kind, state, evidence_ref, created_at, updated_at
    FROM effects_v2""",
    """INSERT INTO reconciliations(
        reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at
    )
    SELECT reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at
    FROM reconciliations_v2 ORDER BY reconciliation_id""",
    """INSERT INTO leases(run_id, effect_id, worker_id, fence, expires_at)
    SELECT run_id, effect_id, worker_id, fence, expires_at FROM leases_v2""",
    "DROP TABLE leases_v2",
    "DROP TABLE reconciliations_v2",
    "DROP TABLE effects_v2",
)
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    0: _BA17_TO_V1_STATEMENTS,
    1: _V1_TO_V2_STATEMENTS,
    2: _V2_TO_V3_STATEMENTS,
}

_V0_COLUMN_SIGNATURES = {
    "runs": (
        ("run_id", "TEXT", 1, 1),
        ("state", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "effects": (
        ("run_id", "TEXT", 1, 1),
        ("effect_id", "TEXT", 1, 2),
        ("kind", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("evidence_ref", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    "leases": (
        ("run_id", "TEXT", 1, 1),
        ("effect_id", "TEXT", 1, 2),
        ("worker_id", "TEXT", 1, 0),
        ("fence", "INTEGER", 1, 0),
        ("expires_at", "TEXT", 1, 0),
    ),
    "events": (
        ("event_id", "INTEGER", 0, 1),
        ("run_id", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0),
        ("event", "TEXT", 1, 0),
        ("state", "TEXT", 1, 0),
        ("context_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}
_CURRENT_COLUMN_SIGNATURES = {
    "journal_metadata": (
        ("singleton", "INTEGER", 0, 1),
        ("schema_version", "INTEGER", 1, 0),
        ("last_observed_time", "TEXT", 0, 0),
    ),
    **_V0_COLUMN_SIGNATURES,
    "reconciliations": (
        ("reconciliation_id", "INTEGER", 0, 1),
        ("run_id", "TEXT", 1, 0),
        ("effect_id", "TEXT", 1, 0),
        ("fence", "INTEGER", 1, 0),
        ("outcome", "TEXT", 1, 0),
        ("evidence_ref", "TEXT", 1, 0),
        ("observed_at", "TEXT", 1, 0),
    ),
}
_CURRENT_INDEXES = frozenset({"idx_effects_run_state", "idx_reconciliations_effect"})
_CURRENT_TRIGGERS = frozenset(
    {
        "runs_revision_must_advance",
        "leases_fence_must_advance",
        "terminal_effects_are_immutable",
        "events_are_immutable_on_update",
        "events_are_immutable_on_delete",
        "reconciliations_are_immutable_on_update",
        "reconciliations_are_immutable_on_delete",
    }
)
_CURRENT_INDEX_MANIFEST = {
    "journal_metadata": frozenset(),
    "runs": frozenset({(1, "pk", 0, ("run_id",))}),
    "effects": frozenset(
        {
            (1, "u", 0, ("effect_id",)),
            (1, "pk", 0, ("run_id", "effect_id")),
            (0, "c", 0, ("run_id", "state")),
        }
    ),
    "leases": frozenset({(1, "pk", 0, ("run_id", "effect_id"))}),
    "events": frozenset({(1, "u", 0, ("run_id", "revision"))}),
    "reconciliations": frozenset(
        {
            (1, "u", 0, ("effect_id", "fence")),
            (0, "c", 0, ("effect_id", "reconciliation_id")),
        }
    ),
}
_V1_INDEX_MANIFEST = {
    **_CURRENT_INDEX_MANIFEST,
    "reconciliations": frozenset(
        {
            (1, "u", 0, ("effect_id", "fence", "outcome", "evidence_ref")),
            (0, "c", 0, ("effect_id", "reconciliation_id")),
        }
    ),
}
_BA17_INDEX_MANIFEST = {
    "runs": _CURRENT_INDEX_MANIFEST["runs"],
    "effects": frozenset(
        {
            (1, "u", 0, ("effect_id",)),
            (1, "pk", 0, ("run_id", "effect_id")),
        }
    ),
    "leases": _CURRENT_INDEX_MANIFEST["leases"],
    "events": _CURRENT_INDEX_MANIFEST["events"],
}
_CURRENT_FOREIGN_KEYS = {
    "journal_metadata": (),
    "runs": (),
    "effects": ((0, 0, "runs", "run_id", "run_id", "NO ACTION", "RESTRICT", "NONE"),),
    "leases": (
        (0, 0, "effects", "run_id", "run_id", "NO ACTION", "RESTRICT", "NONE"),
        (0, 1, "effects", "effect_id", "effect_id", "NO ACTION", "RESTRICT", "NONE"),
    ),
    "events": ((0, 0, "runs", "run_id", "run_id", "NO ACTION", "RESTRICT", "NONE"),),
    "reconciliations": (
        (0, 0, "effects", "run_id", "run_id", "NO ACTION", "RESTRICT", "NONE"),
        (0, 1, "effects", "effect_id", "effect_id", "NO ACTION", "RESTRICT", "NONE"),
    ),
}
_BA17_FOREIGN_KEYS = {
    table: _CURRENT_FOREIGN_KEYS[table]
    for table in ("runs", "effects", "leases", "events")
}


class Journal:
    """Own one SQLite connection and serialize its local write transactions."""

    SCHEMA_VERSION = _CURRENT_SCHEMA_VERSION

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
        connection: sqlite3.Connection | None = None
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
            _initialize_or_migrate(connection)
            _validate_connection_and_schema(connection, busy_timeout_ms)
        except JournalError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise _translate_sqlite(error) from error
        assert connection is not None
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
        with self._authority_transaction() as now:
            effect = self._connection.execute(
                "SELECT state FROM effects WHERE run_id = ? AND effect_id = ?",
                (run_id, effect_id),
            ).fetchone()
            if effect is None:
                raise EffectNotFound(
                    f"effect {effect_id} does not exist for run {run_id}"
                )
            effect_state = EffectState(effect["state"])
            if effect_state is EffectState.COMPLETED:
                raise EffectConflict(
                    f"effect {effect_id} is already {effect_state.value}"
                )

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
        *,
        minimum_lease_ttl: timedelta = timedelta(0),
    ) -> None:
        _require_identifier("effect_id", effect_id)
        if not isinstance(fence, int) or fence <= 0:
            raise StaleFence("fence must be a positive integer")
        if not isinstance(minimum_lease_ttl, timedelta) or minimum_lease_ttl < (
            timedelta(0)
        ):
            raise ValueError("minimum_lease_ttl must be a non-negative timedelta")
        try:
            target = EffectState(state)
        except (TypeError, ValueError) as error:
            raise EffectConflict("unknown effect state") from error
        with self._authority_transaction() as now:
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
                if row["fence"] != fence:
                    raise StaleFence(
                        f"fence {fence} did not commit terminal effect {effect_id}"
                    )
                if row["evidence_ref"] != evidence_ref:
                    raise EffectConflict(
                        "effect evidence conflicts with durable evidence"
                    )
                return
            if (
                row["fence"] is None
                or row["fence"] != fence
                or _parse_time(row["expires_at"]) <= now + minimum_lease_ttl
            ):
                raise StaleFence(f"fence {fence} is not current for effect {effect_id}")

            if current is target:
                if row["evidence_ref"] != evidence_ref:
                    raise EffectConflict(
                        "effect evidence conflicts with durable evidence"
                    )
                return

            allowed = {
                EffectState.INTENT: {EffectState.STARTED},
                EffectState.STARTED: {
                    EffectState.PREPARED,
                    EffectState.COMPLETED,
                },
                EffectState.PREPARED: {EffectState.COMPLETED},
                EffectState.COMPLETED: set(),
                EffectState.RECONCILED: set(),
            }
            if target not in allowed[current]:
                raise EffectConflict(
                    f"effect cannot transition from {current.value} to {target.value}"
                )
            if target is EffectState.STARTED and evidence_ref is not None:
                raise EffectConflict("started effect cannot carry completion evidence")
            if target in {
                EffectState.PREPARED,
                EffectState.COMPLETED,
                EffectState.RECONCILED,
            } and (not isinstance(evidence_ref, str) or not evidence_ref.strip()):
                raise EffectConflict(f"{target.value} effect requires evidence")

            self._connection.execute(
                "UPDATE effects SET state = ?, evidence_ref = ?, updated_at = ? "
                "WHERE effect_id = ?",
                (target.value, evidence_ref, _format_time(now), effect_id),
            )

    def adopt_prepared(
        self,
        effect_id: str,
        fence: int,
        prior_evidence_ref: str,
        adopted_evidence_ref: str,
    ) -> None:
        """Atomically rebind a durable stage to the current live retry fence."""
        _require_identifier("effect_id", effect_id)
        if not isinstance(fence, int) or fence <= 0:
            raise StaleFence("fence must be a positive integer")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (prior_evidence_ref, adopted_evidence_ref)
        ):
            raise EffectConflict("prepared adoption requires durable evidence")
        with self._authority_transaction() as now:
            row = self._connection.execute(
                "SELECT e.state, e.evidence_ref, l.fence, l.expires_at "
                "FROM effects e LEFT JOIN leases l "
                "ON l.run_id = e.run_id AND l.effect_id = e.effect_id "
                "WHERE e.effect_id = ?",
                (effect_id,),
            ).fetchone()
            if row is None:
                raise EffectNotFound(f"effect {effect_id} does not exist")
            if EffectState(row["state"]) is not EffectState.PREPARED:
                raise EffectConflict("only a prepared effect can be adopted")
            if row["evidence_ref"] == adopted_evidence_ref:
                if row["fence"] != fence:
                    raise StaleFence("prepared adoption fence is no longer current")
                return
            if row["evidence_ref"] != prior_evidence_ref:
                raise EffectConflict("prepared adoption evidence conflicts")
            if (
                row["fence"] is None
                or row["fence"] != fence
                or _parse_time(row["expires_at"]) <= now
            ):
                raise StaleFence("prepared adoption fence is not live")
            self._connection.execute(
                "UPDATE effects SET evidence_ref = ?, updated_at = ? "
                "WHERE effect_id = ? AND state = ? AND evidence_ref = ?",
                (
                    adopted_evidence_ref,
                    _format_time(now),
                    effect_id,
                    EffectState.PREPARED.value,
                    prior_evidence_ref,
                ),
            )

    def record_reconciliation(
        self,
        effect_id: str,
        fence: int,
        outcome: ReconciliationOutcome,
        evidence_ref: str | None,
    ) -> ReconciliationRecord:
        _require_identifier("effect_id", effect_id)
        if not isinstance(fence, int) or fence <= 0:
            raise StaleFence("fence must be a positive integer")
        try:
            normalized_outcome = ReconciliationOutcome(outcome)
        except (TypeError, ValueError) as error:
            raise EffectConflict("unknown reconciliation outcome") from error
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise EffectConflict(
                f"{normalized_outcome.value} reconciliation requires probe evidence"
            )

        with self._authority_transaction() as now:
            prior_reconciliations = self._connection.execute(
                "SELECT reconciliation_id, run_id, effect_id, fence, outcome, "
                "evidence_ref, observed_at FROM reconciliations "
                "WHERE effect_id = ? AND fence = ? ORDER BY reconciliation_id",
                (effect_id, fence),
            ).fetchall()
            if prior_reconciliations:
                if len(prior_reconciliations) == 1:
                    prior = prior_reconciliations[0]
                    if (
                        prior["outcome"] == normalized_outcome.value
                        and prior["evidence_ref"] == evidence_ref
                    ):
                        return _reconciliation_from_row(prior)
                raise EffectConflict(
                    "reconciliation conflicts with durable reconciliation"
                )
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
            if current is EffectState.COMPLETED:
                if row["fence"] != fence:
                    raise StaleFence(
                        f"fence {fence} did not commit terminal effect {effect_id}"
                    )
                raise EffectConflict("completed reconciliation evidence is immutable")
            if current not in {
                EffectState.STARTED,
                EffectState.PREPARED,
                EffectState.RECONCILED,
            }:
                raise EffectConflict(
                    f"effect in {current.value} does not require reconciliation"
                )
            if (
                row["fence"] is None
                or row["fence"] != fence
                or _parse_time(row["expires_at"]) <= now
            ):
                raise StaleFence(f"fence {fence} is not current for effect {effect_id}")

            cursor = self._connection.execute(
                "INSERT INTO reconciliations(run_id, effect_id, fence, outcome, evidence_ref, observed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["run_id"],
                    effect_id,
                    fence,
                    normalized_outcome.value,
                    evidence_ref,
                    _format_time(now),
                ),
            )
            if normalized_outcome is ReconciliationOutcome.OBSERVED_COMPLETED:
                self._connection.execute(
                    "UPDATE effects SET state = ?, evidence_ref = ?, updated_at = ? "
                    "WHERE effect_id = ?",
                    (
                        EffectState.COMPLETED.value,
                        evidence_ref,
                        _format_time(now),
                        effect_id,
                    ),
                )
            elif normalized_outcome is ReconciliationOutcome.OBSERVED_ABSENT:
                if current is not EffectState.PREPARED:
                    self._connection.execute(
                        "UPDATE effects SET state = ?, evidence_ref = NULL, updated_at = ? "
                        "WHERE effect_id = ?",
                        (EffectState.INTENT.value, _format_time(now), effect_id),
                    )
                self._connection.execute(
                    "UPDATE leases SET expires_at = ? WHERE run_id = ? AND effect_id = ?",
                    (_format_time(now), row["run_id"], effect_id),
                )
            else:
                self._connection.execute(
                    "UPDATE effects SET state = ?, evidence_ref = NULL, updated_at = ? "
                    "WHERE effect_id = ?",
                    (EffectState.RECONCILED.value, _format_time(now), effect_id),
                )

            return ReconciliationRecord(
                cursor.lastrowid,
                row["run_id"],
                effect_id,
                fence,
                normalized_outcome,
                evidence_ref,
                now,
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

    def list_reconciliations(self, effect_id: str) -> tuple[ReconciliationRecord, ...]:
        rows = self._execute_read(
            "SELECT reconciliation_id, run_id, effect_id, fence, outcome, "
            "evidence_ref, observed_at FROM reconciliations "
            "WHERE effect_id = ? ORDER BY reconciliation_id",
            (effect_id,),
        ).fetchall()
        return tuple(_reconciliation_from_row(row) for row in rows)

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

    @contextmanager
    def _authority_transaction(self) -> Iterator[datetime]:
        pending_error: JournalError | None = None
        with self._write_lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                now = self._now()
                _advance_observed_time(self._connection, now)
                self._connection.execute("SAVEPOINT authority_mutation")
                try:
                    yield now
                except JournalError as error:
                    self._connection.execute("ROLLBACK TO authority_mutation")
                    self._connection.execute("RELEASE authority_mutation")
                    pending_error = error
                else:
                    self._connection.execute("RELEASE authority_mutation")
                self._connection.commit()
            except sqlite3.Error as error:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise _translate_sqlite(error) from error
            except Exception:
                if self._connection.in_transaction:
                    self._connection.rollback()
                raise
        if pending_error is not None:
            raise pending_error

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


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


def _initialize_or_migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > _CURRENT_SCHEMA_VERSION:
        raise JournalStorageError(f"future journal schema version {version}")

    tables = _object_names(connection, "table")
    if version == 0 and not tables:
        _apply_schema_steps(
            connection,
            _CURRENT_SCHEMA_STATEMENTS,
            target_version=_CURRENT_SCHEMA_VERSION,
            label="initialization",
        )
        return
    if version == 0 and not _is_known_v0(connection):
        raise JournalStorageError("unknown or partial unversioned journal schema")

    while version < _CURRENT_SCHEMA_VERSION:
        statements = _MIGRATIONS.get(version)
        if statements is None:
            raise JournalStorageError(
                f"unsupported journal schema migration from version {version}"
            )
        _apply_schema_steps(
            connection,
            statements,
            source_version=version,
            target_version=version + 1,
            label=f"migration {version}->{version + 1}",
        )
        version += 1


def _apply_schema_steps(
    connection: sqlite3.Connection,
    statements: tuple[str, ...],
    *,
    source_version: int | None = None,
    target_version: int,
    label: str,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        if source_version == 1:
            if not _is_known_v1(connection):
                raise JournalStorageError("unknown journal schema version 1")
            duplicate = connection.execute(
                "SELECT effect_id, fence FROM reconciliations "
                "GROUP BY effect_id, fence HAVING COUNT(*) > 1 LIMIT 1"
            ).fetchone()
            if duplicate is not None:
                raise JournalStorageError(
                    "duplicate reconciliation command identity in version 1 journal"
                )
        for statement in statements:
            connection.execute(statement)
        updated = connection.execute(
            "UPDATE journal_metadata SET schema_version = ? WHERE singleton = 1",
            (target_version,),
        )
        if updated.rowcount != 1:
            raise sqlite3.DatabaseError("schema metadata row was not created")
        connection.execute(f"PRAGMA user_version = {target_version}")
        connection.commit()
    except JournalStorageError:
        if connection.in_transaction:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection.in_transaction:
            connection.rollback()
        raise JournalStorageError(f"journal schema {label} failed") from error


def _is_known_v0(connection: sqlite3.Connection) -> bool:
    if _object_names(connection, "table") != frozenset(_V0_COLUMN_SIGNATURES):
        return False
    if _database_sql_manifest(connection) != _BA17_SQL_MANIFEST:
        return False
    if any(
        _index_semantics(connection, table) != expected
        for table, expected in _BA17_INDEX_MANIFEST.items()
    ):
        return False
    if any(
        _foreign_keys(connection, table) != expected
        for table, expected in _BA17_FOREIGN_KEYS.items()
    ):
        return False
    return all(
        _table_signature(connection, table) == signature
        for table, signature in _V0_COLUMN_SIGNATURES.items()
    )


def _is_known_v1(connection: sqlite3.Connection) -> bool:
    if _object_names(connection, "table") != frozenset(_CURRENT_COLUMN_SIGNATURES):
        return False
    if _object_names(connection, "index") != _CURRENT_INDEXES:
        return False
    if _object_names(connection, "trigger") != _CURRENT_TRIGGERS:
        return False
    if _database_sql_manifest(connection) != _V1_SQL_MANIFEST:
        return False
    if any(
        _table_signature(connection, table) != signature
        for table, signature in _CURRENT_COLUMN_SIGNATURES.items()
    ):
        return False
    if any(
        _index_semantics(connection, table) != expected
        for table, expected in _V1_INDEX_MANIFEST.items()
    ):
        return False
    if any(
        _foreign_keys(connection, table) != expected
        for table, expected in _CURRENT_FOREIGN_KEYS.items()
    ):
        return False
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        return False
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        return False
    metadata = connection.execute(
        "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
    ).fetchone()
    return metadata is not None and metadata[0] == 1


def _validate_connection_and_schema(
    connection: sqlite3.Connection, busy_timeout_ms: int
) -> None:
    settings = {
        "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
        "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
        "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
        "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
    }
    if (
        settings["foreign_keys"] != 1
        or str(settings["journal_mode"]).lower() != "wal"
        or settings["busy_timeout"] != busy_timeout_ms
        or settings["synchronous"] != 2
    ):
        raise JournalStorageError("journal schema validation failed: connection PRAGMA")

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != _CURRENT_SCHEMA_VERSION:
        raise JournalStorageError("journal schema validation failed: user_version")
    if _object_names(connection, "table") != frozenset(_CURRENT_COLUMN_SIGNATURES):
        raise JournalStorageError("journal schema validation failed: tables")
    for table, signature in _CURRENT_COLUMN_SIGNATURES.items():
        if _table_signature(connection, table) != signature:
            raise JournalStorageError(
                f"journal schema validation failed: columns for {table}"
            )
    if _CURRENT_INDEXES != _object_names(connection, "index"):
        raise JournalStorageError("journal schema validation failed: indexes")
    if _CURRENT_TRIGGERS != _object_names(connection, "trigger"):
        raise JournalStorageError("journal schema validation failed: triggers")
    if _database_sql_manifest(connection) != _CURRENT_SQL_MANIFEST:
        raise JournalStorageError("journal schema validation failed: object SQL")
    for table, expected in _CURRENT_INDEX_MANIFEST.items():
        if _index_semantics(connection, table) != expected:
            raise JournalStorageError(
                f"journal schema validation failed: indexes for {table}"
            )
    for table, expected in _CURRENT_FOREIGN_KEYS.items():
        if _foreign_keys(connection, table) != expected:
            raise JournalStorageError(
                f"journal schema validation failed: foreign keys for {table}"
            )
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise JournalStorageError("journal schema validation failed: foreign key data")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise JournalStorageError("journal schema validation failed: quick check")
    metadata = connection.execute(
        "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
    ).fetchone()
    if metadata is None or metadata[0] != _CURRENT_SCHEMA_VERSION:
        raise JournalStorageError("journal schema validation failed: metadata version")


def _object_names(connection: sqlite3.Connection, kind: str) -> frozenset[str]:
    return frozenset(
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
            (kind,),
        )
    )


def _table_signature(
    connection: sqlite3.Connection, table: str
) -> tuple[tuple[str, str, int, int], ...]:
    safe_table = table.replace('"', '""')
    return tuple(
        (row[1], row[2].upper(), row[3], row[5])
        for row in connection.execute(f'PRAGMA table_info("{safe_table}")').fetchall()
    )


def _database_sql_manifest(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    return {
        (row[0], row[1]): _normalize_schema_sql(row[2])
        for row in connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger') "
            "AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
        )
    }


def _index_semantics(
    connection: sqlite3.Connection, table: str
) -> frozenset[tuple[int, str, int, tuple[str, ...]]]:
    safe_table = table.replace('"', '""')
    result = set()
    for row in connection.execute(f'PRAGMA index_list("{safe_table}")').fetchall():
        safe_index = row[1].replace('"', '""')
        columns = tuple(
            item[2]
            for item in connection.execute(
                f'PRAGMA index_info("{safe_index}")'
            ).fetchall()
        )
        result.add((row[2], row[3], row[4], columns))
    return frozenset(result)


def _foreign_keys(
    connection: sqlite3.Connection, table: str
) -> tuple[tuple[object, ...], ...]:
    safe_table = table.replace('"', '""')
    return tuple(
        tuple(row)
        for row in connection.execute(
            f'PRAGMA foreign_key_list("{safe_table}")'
        ).fetchall()
    )


def _advance_observed_time(
    connection: sqlite3.Connection, observed_at: datetime
) -> None:
    row = connection.execute(
        "SELECT last_observed_time FROM journal_metadata WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise JournalStorageError("journal schema validation failed: metadata row")
    persisted = _parse_time(row[0]) if row[0] is not None else None
    if persisted is not None and observed_at < persisted:
        raise ClockRollback(
            f"clock moved backwards from {_format_time(persisted)} to {_format_time(observed_at)}"
        )
    if persisted is None or observed_at > persisted:
        connection.execute(
            "UPDATE journal_metadata SET last_observed_time = ? WHERE singleton = 1",
            (_format_time(observed_at),),
        )


def _translate_sqlite(error: sqlite3.Error) -> JournalError:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return DatabaseBusy("journal database is busy")
    return JournalStorageError("journal storage operation failed")


def _reconciliation_from_row(row: sqlite3.Row) -> ReconciliationRecord:
    return ReconciliationRecord(
        row["reconciliation_id"],
        row["run_id"],
        row["effect_id"],
        row["fence"],
        ReconciliationOutcome(row["outcome"]),
        row["evidence_ref"],
        _parse_time(row["observed_at"]),
    )
