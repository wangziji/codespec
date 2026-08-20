from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import codex_contract_delivery.journal as journal_module
import pytest
from codex_contract_delivery.journal import (
    AdmissionExpired,
    ClockRollback,
    DatabaseBusy,
    EffectConflict,
    EffectIntent,
    EffectState,
    ExecutionAuthority,
    Journal,
    JournalError,
    JournalStorageError,
    LeaseHeld,
    ReconciliationOutcome,
    ReconciliationRequired,
    RevisionConflict,
    StaleFence,
    TransitionRequest,
)
from codex_contract_delivery.state_machine import InvalidTransition, RunEvent, RunState


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class AdvancingClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
        self.calls = 0

    def __call__(self) -> datetime:
        observed = self.now
        self.now += timedelta(seconds=1)
        self.calls += 1
        return observed


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


def observed_watermark(path: Path) -> str | None:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT last_observed_time FROM journal_metadata WHERE singleton = 1"
        ).fetchone()[0]
    finally:
        connection.close()


def lease_row(path: Path) -> tuple[str, int, str]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT worker_id, fence, expires_at FROM leases "
            "WHERE run_id = 'run-1' AND effect_id = 'deploy-1'"
        ).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()


def create_ba17dca_v0_database(path: Path, *, revision_type: str = "INTEGER") -> None:
    """Create the exact unversioned schema shipped by commit ba17dca."""
    connection = sqlite3.connect(path)
    script = """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY CHECK(length(run_id) > 0),
            state TEXT NOT NULL CHECK(state IN ('new', 'discovery', 'requirements', 'gate_1', 'design', 'modules', 'gate_2', 'planning', 'gate_3', 'implementation', 'verification', 'test', 'production_authorization', 'prod', 'acceptance', 'completed', 'incident', 'correction', 'rollback', 'safe_checkpoint')),
            revision __REVISION_TYPE__ NOT NULL CHECK(revision >= 0),
            updated_at TEXT NOT NULL
        ) STRICT;
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
        ) STRICT;
        CREATE TABLE leases (
            run_id TEXT NOT NULL,
            effect_id TEXT NOT NULL,
            worker_id TEXT NOT NULL CHECK(length(worker_id) > 0),
            fence INTEGER NOT NULL CHECK(fence > 0),
            expires_at TEXT NOT NULL,
            PRIMARY KEY (run_id, effect_id),
            FOREIGN KEY (run_id, effect_id) REFERENCES effects(run_id, effect_id)
                ON DELETE RESTRICT
        ) STRICT;
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision > 0),
            event TEXT NOT NULL CHECK(event IN ('DISCOVER', 'DRAFT_REQUIREMENTS', 'APPROVE_GATE_1', 'DESIGN', 'DEFINE_MODULES', 'APPROVE_GATE_2', 'PLAN', 'APPROVE_GATE_3', 'IMPLEMENT', 'VERIFY', 'RELEASE_TEST', 'REQUEST_PRODUCTION', 'RELEASE_PRODUCTION', 'ACCEPT', 'APPROVE_GATE_4', 'INVALIDATE_DEPENDENCY', 'RECORD_INCIDENT', 'CORRECT', 'ROLLBACK', 'ENTER_SAFE_CHECKPOINT')),
            state TEXT NOT NULL CHECK(state IN ('new', 'discovery', 'requirements', 'gate_1', 'design', 'modules', 'gate_2', 'planning', 'gate_3', 'implementation', 'verification', 'test', 'production_authorization', 'prod', 'acceptance', 'completed', 'incident', 'correction', 'rollback', 'safe_checkpoint')),
            context_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, revision),
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT
        ) STRICT;
        CREATE TRIGGER runs_revision_must_advance
        BEFORE UPDATE ON runs
        WHEN NEW.revision != OLD.revision + 1
        BEGIN SELECT RAISE(ABORT, 'run revision must advance by one'); END;
        CREATE TRIGGER leases_fence_must_advance
        BEFORE UPDATE ON leases
        WHEN NEW.fence <= OLD.fence
        BEGIN SELECT RAISE(ABORT, 'lease fence must increase'); END;
        CREATE TRIGGER terminal_effects_are_immutable
        BEFORE UPDATE ON effects
        WHEN OLD.state IN ('completed', 'reconciled')
        BEGIN SELECT RAISE(ABORT, 'terminal effect is immutable'); END;
        CREATE TRIGGER events_are_immutable_on_update
        BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'journal events are immutable'); END;
        CREATE TRIGGER events_are_immutable_on_delete
        BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'journal events are immutable'); END;
        PRAGMA user_version = 0;
        """.replace("__REVISION_TYPE__", revision_type)
    connection.executescript(script)
    connection.execute(
        "INSERT INTO runs(run_id, state, revision, updated_at) VALUES (?, ?, ?, ?)",
        ("run-1", "discovery", 1, "2026-08-11T00:00:00.000000+00:00"),
    )
    for effect_id, state, evidence in (
        ("intent-effect", "intent", None),
        ("started-effect", "started", None),
        ("completed-effect", "completed", "evidence://completed"),
        ("reconciled-effect", "reconciled", "evidence://legacy-reconciled"),
    ):
        connection.execute(
            "INSERT INTO effects(run_id, effect_id, kind, state, evidence_ref, created_at, updated_at) "
            "VALUES ('run-1', ?, 'release', ?, ?, ?, ?)",
            (
                effect_id,
                state,
                evidence,
                "2026-08-11T00:00:00.000000+00:00",
                "2026-08-11T00:00:00.000000+00:00",
            ),
        )
    for effect_id, worker_id, fence in (
        ("started-effect", "worker-started", 7),
        ("reconciled-effect", "worker-reconciled", 8),
    ):
        connection.execute(
            "INSERT INTO leases(run_id, effect_id, worker_id, fence, expires_at) "
            "VALUES ('run-1', ?, ?, ?, '2026-08-11T00:01:00.000000+00:00')",
            (effect_id, worker_id, fence),
        )
    connection.execute(
        "INSERT INTO events(run_id, revision, event, state, context_json, created_at) "
        "VALUES ('run-1', 1, 'DISCOVER', 'discovery', '{}', '2026-08-11T00:00:00.000000+00:00')"
    )
    connection.commit()
    connection.close()


def create_round2_v1_database(path: Path, *, conflicting: bool = False) -> None:
    """Create the exact schema published by round 2 with durable audit data."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    for statement in journal_module._V1_SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.execute("PRAGMA user_version = 1")
    timestamp = "2026-08-11T00:00:00.000000+00:00"
    connection.execute(
        "INSERT INTO runs(run_id, state, revision, updated_at) "
        "VALUES ('run-1', 'discovery', 1, ?)",
        (timestamp,),
    )
    connection.execute(
        "INSERT INTO events(run_id, revision, event, state, context_json, created_at) "
        "VALUES ('run-1', 1, 'DISCOVER', 'discovery', '{}', ?)",
        (timestamp,),
    )
    for effect_id, state, evidence in (
        ("reconciled-effect", "reconciled", None),
        ("completed-effect", "completed", "probe://completed"),
    ):
        connection.execute(
            "INSERT INTO effects(run_id, effect_id, kind, state, evidence_ref, created_at, updated_at) "
            "VALUES ('run-1', ?, 'release', ?, ?, ?, ?)",
            (effect_id, state, evidence, timestamp, timestamp),
        )
    for effect_id, worker_id, fence in (
        ("reconciled-effect", "worker-a", 7),
        ("completed-effect", "worker-b", 8),
    ):
        connection.execute(
            "INSERT INTO leases(run_id, effect_id, worker_id, fence, expires_at) "
            "VALUES ('run-1', ?, ?, ?, ?)",
            (effect_id, worker_id, fence, timestamp),
        )
    connection.execute(
        "INSERT INTO reconciliations(reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at) "
        "VALUES (41, 'run-1', 'reconciled-effect', 7, 'unknown', 'probe://unknown', ?)",
        (timestamp,),
    )
    connection.execute(
        "INSERT INTO reconciliations(reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at) "
        "VALUES (44, 'run-1', 'completed-effect', 8, 'observed_completed', 'probe://completed', ?)",
        (timestamp,),
    )
    if conflicting:
        connection.execute(
            "INSERT INTO reconciliations(reconciliation_id, run_id, effect_id, fence, outcome, evidence_ref, observed_at) "
            "VALUES (45, 'run-1', 'reconciled-effect', 7, 'observed_absent', 'probe://absent', ?)",
            (timestamp,),
        )
    connection.commit()
    connection.close()


def rewrite_schema_object(path: Path, kind: str, name: str, sql: str) -> None:
    """Replace one sqlite_master definition to build a same-shape corrupt fixture."""
    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA schema_version").fetchone()[0]
    connection.execute("PRAGMA writable_schema = ON")
    connection.execute(
        "UPDATE sqlite_master SET sql = ? WHERE type = ? AND name = ?",
        (sql, kind, name),
    )
    connection.execute("PRAGMA writable_schema = OFF")
    connection.execute(f"PRAGMA schema_version = {version + 1}")
    connection.commit()
    connection.close()


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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 3
        )
    finally:
        connection.close()


def test_open_migrates_real_ba17dca_schema_and_preserves_data(
    journal_path: Path,
) -> None:
    """Would fail if migration did not preserve the real ba17dca journal data."""
    create_ba17dca_v0_database(journal_path)

    migrated = Journal.open(journal_path)
    try:
        assert migrated.get_run("run-1").revision == 1
        assert (
            migrated.get_effect("run-1", "started-effect").state is EffectState.STARTED
        )
        assert migrated.get_effect("run-1", "completed-effect").evidence_ref == (
            "evidence://completed"
        )
        assert migrated.get_effect("run-1", "reconciled-effect").state is (
            EffectState.RECONCILED
        )
        assert migrated.list_reconciliations("reconciled-effect")[0].outcome is (
            ReconciliationOutcome.UNKNOWN
        )
    finally:
        migrated.close()

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 3
        )
        assert dict(connection.execute("SELECT effect_id, fence FROM leases")) == {
            "started-effect": 7,
            "reconciled-effect": 8,
        }
    finally:
        connection.close()

    reopened = Journal.open(journal_path)
    reopened.close()


def test_open_migrates_clean_round2_v1_and_preserves_audit_identity(
    journal_path: Path,
) -> None:
    """Would fail if v1-to-v2 migration changed audit IDs, order, or evidence."""
    create_round2_v1_database(journal_path)

    migrated = Journal.open(journal_path)
    migrated.close()

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 3
        )
        assert connection.execute(
            "SELECT reconciliation_id, effect_id, fence, outcome, evidence_ref "
            "FROM reconciliations ORDER BY reconciliation_id"
        ).fetchall() == [
            (41, "reconciled-effect", 7, "unknown", "probe://unknown"),
            (44, "completed-effect", 8, "observed_completed", "probe://completed"),
        ]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE run_id = 'run-1' AND revision = 1"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT fence FROM leases WHERE effect_id = 'completed-effect'"
            ).fetchone()[0]
            == 8
        )
        assert (
            "UNIQUE (effect_id, fence)"
            in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'reconciliations'"
            ).fetchone()[0]
        )
    finally:
        connection.close()

    reopened = Journal.open(journal_path)
    reopened.close()


def test_open_migrates_exact_v2_manifest_to_v3_prepared_state(
    journal_path: Path,
) -> None:
    """Would fail if the deployed v2 manifest could not reach PREPARED safely."""
    connection = sqlite3.connect(journal_path)
    try:
        connection.executescript(journal_module._V2_SCHEMA)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()

    migrated = Journal.open(journal_path)
    try:
        seed_effect(migrated)
        lease = migrated.acquire_attempt(
            "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
        )
        stage = "effect-stage://sha256/" + "a" * 64
        migrated.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
        migrated.record_effect("deploy-1", lease.fence, EffectState.PREPARED, stage)
        effect = migrated.get_effect("run-1", "deploy-1")
        assert effect is not None and effect.evidence_ref == stage
    finally:
        migrated.close()

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 3
        )
    finally:
        connection.close()


def test_open_rejects_partial_unversioned_ddl_without_modifying_it(
    journal_path: Path,
) -> None:
    """Would fail if CREATE IF NOT EXISTS blessed a partial database as current."""
    connection = sqlite3.connect(journal_path)
    connection.execute("CREATE TABLE runs (wrong_column TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="unknown or partial"):
        Journal.open(journal_path)

    connection = sqlite3.connect(journal_path)
    try:
        assert [row[1] for row in connection.execute("PRAGMA table_info(runs)")] == [
            "wrong_column"
        ]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        connection.close()


def test_open_rejects_unknown_v0_with_same_column_names_but_wrong_types(
    journal_path: Path,
) -> None:
    """Would fail if column names alone could impersonate the supported v0 fixture."""
    create_ba17dca_v0_database(journal_path, revision_type="TEXT")

    with pytest.raises(JournalStorageError, match="unknown or partial"):
        Journal.open(journal_path)


def test_open_rejects_future_schema_version(journal_path: Path) -> None:
    """Would fail if an older runtime silently opened a journal with unknown semantics."""
    connection = sqlite3.connect(journal_path)
    connection.execute("PRAGMA user_version = 99")
    connection.close()

    with pytest.raises(JournalStorageError, match="future journal schema version 99"):
        Journal.open(journal_path)


def test_failed_migration_rolls_back_every_statement(
    journal_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Would fail if migration DDL committed before a later statement failed."""
    create_ba17dca_v0_database(journal_path)
    migration = journal_module._MIGRATIONS[0]
    monkeypatch.setattr(
        journal_module,
        "_MIGRATIONS",
        {0: (*migration[:8], "INVALID SQL", *migration[8:])},
    )

    with pytest.raises(JournalStorageError, match="migration"):
        Journal.open(journal_path)

    connection = sqlite3.connect(journal_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "effects_ba17dca" not in tables
        assert "leases_ba17dca" not in tables
        assert (
            connection.execute(
                "SELECT state FROM effects WHERE effect_id = 'started-effect'"
            ).fetchone()[0]
            == "started"
        )
        assert (
            connection.execute(
                "SELECT fence FROM leases WHERE effect_id = 'started-effect'"
            ).fetchone()[0]
            == 7
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'trigger' AND name = 'terminal_effects_are_immutable'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        connection.close()


def test_reopen_revalidates_required_schema_objects(journal_path: Path) -> None:
    """Would fail if a version number hid a missing required trigger or index."""
    created = Journal.open(journal_path)
    created.close()
    connection = sqlite3.connect(journal_path)
    connection.execute("DROP TRIGGER events_are_immutable_on_update")
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="schema validation"):
        Journal.open(journal_path)


def test_reopen_rejects_unrecognized_trigger_even_when_version_is_current(
    journal_path: Path,
) -> None:
    """Would fail if a rogue trigger could alter writes behind a valid version marker."""
    created = Journal.open(journal_path)
    created.close()
    connection = sqlite3.connect(journal_path)
    connection.execute(
        "CREATE TRIGGER rogue_run_trigger BEFORE INSERT ON runs "
        "BEGIN SELECT RAISE(ABORT, 'rogue'); END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="schema validation"):
        Journal.open(journal_path)


def test_reopen_rejects_same_name_trigger_with_empty_body(journal_path: Path) -> None:
    """Would fail if trigger names hid weakened enforcement bodies."""
    created = Journal.open(journal_path)
    created.close()
    connection = sqlite3.connect(journal_path)
    connection.execute("DROP TRIGGER terminal_effects_are_immutable")
    connection.execute(
        "CREATE TRIGGER terminal_effects_are_immutable BEFORE UPDATE ON effects "
        "BEGIN SELECT 1; END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="schema validation"):
        Journal.open(journal_path)


def test_reopen_rejects_effects_table_without_check_or_foreign_key(
    journal_path: Path,
) -> None:
    """Would fail if matching column signatures hid removed CHECK and FK semantics."""
    created = Journal.open(journal_path)
    created.close()
    rewrite_schema_object(
        journal_path,
        "table",
        "effects",
        """CREATE TABLE effects (
            run_id TEXT NOT NULL,
            effect_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            evidence_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, effect_id)
        ) STRICT""",
    )

    with pytest.raises(JournalStorageError, match="schema validation"):
        Journal.open(journal_path)


@pytest.mark.parametrize(
    "replacement",
    [
        "CREATE INDEX idx_effects_run_state ON effects(state)",
        "CREATE UNIQUE INDEX idx_effects_run_state ON effects(run_id, state)",
    ],
)
def test_reopen_rejects_same_name_index_with_wrong_columns_or_uniqueness(
    journal_path: Path, replacement: str
) -> None:
    """Would fail if index names hid wrong columns or uniqueness semantics."""
    created = Journal.open(journal_path)
    created.close()
    connection = sqlite3.connect(journal_path)
    connection.execute("DROP INDEX idx_effects_run_state")
    connection.execute(replacement)
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="schema validation"):
        Journal.open(journal_path)


def test_conflicting_round2_v1_migration_fails_closed_and_rolls_back(
    journal_path: Path,
) -> None:
    """Would fail if migration guessed a winner for one contradictory v1 command."""
    create_round2_v1_database(journal_path, conflicting=True)

    with pytest.raises(JournalStorageError, match="duplicate reconciliation command"):
        Journal.open(journal_path)

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute(
            "SELECT reconciliation_id, outcome FROM reconciliations "
            "WHERE effect_id = 'reconciled-effect' AND fence = 7 "
            "ORDER BY reconciliation_id"
        ).fetchall() == [(41, "unknown"), (45, "observed_absent")]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'reconciliations_v1'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_unknown_version_1_manifest_is_rejected_without_migration(
    journal_path: Path,
) -> None:
    """Would fail if user_version alone authorized a weakened v1 migration source."""
    create_round2_v1_database(journal_path)
    connection = sqlite3.connect(journal_path)
    connection.execute("DROP TRIGGER reconciliations_are_immutable_on_update")
    connection.execute(
        "CREATE TRIGGER reconciliations_are_immutable_on_update "
        "BEFORE UPDATE ON reconciliations BEGIN SELECT 1; END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="unknown journal schema version 1"):
        Journal.open(journal_path)

    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT schema_version FROM journal_metadata WHERE singleton = 1"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_v2_database_rejects_direct_duplicate_reconciliation_command(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if v2 did not enforce command identity below the API."""
    created = Journal.open(journal_path, clock=clock)
    seed_effect(created)
    lease = created.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    created.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    created.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://unknown",
    )
    created.close()

    connection = sqlite3.connect(journal_path)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        connection.execute(
            "INSERT INTO reconciliations(run_id, effect_id, fence, outcome, evidence_ref, observed_at) "
            "VALUES ('run-1', 'deploy-1', ?, 'observed_absent', 'probe://absent', ?)",
            (lease.fence, clock.now.isoformat(timespec="microseconds")),
        )
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


def test_clock_rollback_across_reopen_is_rejected_before_lease_decision(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if wall-clock rollback silently extended or revived lease authority."""
    first = Journal.open(journal_path, clock=clock)
    seed_effect(first)
    first.acquire_attempt("run-1", "deploy-1", "worker-a", timedelta(seconds=0))
    first.close()
    clock.now -= timedelta(seconds=1)

    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(JournalError, match="clock moved backwards"):
            reopened.acquire_attempt(
                "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
            )
    finally:
        reopened.close()


def test_future_lease_held_result_commits_watermark_before_raising(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if an expected LeaseHeld rolled back the newly observed max time."""
    first = Journal.open(journal_path, clock=clock)
    seed_effect(first)
    first.acquire_attempt("run-1", "deploy-1", "worker-a", timedelta(minutes=10))
    clock.advance(timedelta(minutes=5))
    with pytest.raises(LeaseHeld):
        first.acquire_attempt("run-1", "deploy-1", "worker-b", timedelta(minutes=1))
    first.close()
    clock.now -= timedelta(minutes=4)

    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(JournalError, match="clock moved backwards"):
            reopened.acquire_attempt(
                "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
            )
    finally:
        reopened.close()


def test_clock_rollback_rejects_old_owner_effect_mutation(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if wall-clock rollback let an owner extend STARTED authority."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    clock.now -= timedelta(seconds=1)

    with pytest.raises(JournalError, match="clock moved backwards"):
        journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)

    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT


def test_clock_rollback_rejects_old_owner_reconciliation_mutation(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if wall-clock rollback could append a reconciliation outcome."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    clock.now -= timedelta(seconds=1)

    with pytest.raises(JournalError, match="clock moved backwards"):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.UNKNOWN,
            "probe://timeout",
        )

    assert journal.list_reconciliations("deploy-1") == ()


def test_exact_same_observed_time_allows_effect_and_reconciliation_mutations(
    journal: Journal,
) -> None:
    """Would fail if equality with the watermark were mistaken for rollback."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://same-time",
    )

    assert journal.list_reconciliations("deploy-1")[0].outcome is (
        ReconciliationOutcome.UNKNOWN
    )


def test_each_authority_action_samples_clock_exactly_once(journal_path: Path) -> None:
    """Would fail if one decision compared or stored different clock samples."""
    clock = AdvancingClock()
    journal = Journal.open(journal_path, clock=clock)
    seed_effect(journal, "effect-1")
    clock.calls = 0
    first = journal.acquire_attempt(
        "run-1", "effect-1", "worker-a", timedelta(minutes=1)
    )
    assert clock.calls == 1

    clock.calls = 0
    journal.record_effect("effect-1", first.fence, EffectState.STARTED, None)
    assert clock.calls == 1

    clock.calls = 0
    journal.record_reconciliation(
        "effect-1",
        first.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://single-sample",
    )
    assert clock.calls == 1
    journal.close()


def test_stale_fence_denial_commits_watermark_without_effect_or_lease_mutation(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if stale authority denial rolled back its observed time."""
    journal = Journal.open(journal_path, clock=clock)
    seed_effect(journal)
    stale = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=0)
    )
    current = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )
    clock.advance(timedelta(seconds=10))
    denied_at = clock.now

    with pytest.raises(StaleFence):
        journal.record_effect("deploy-1", stale.fence, EffectState.STARTED, None)

    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    connection = sqlite3.connect(journal_path)
    try:
        assert connection.execute(
            "SELECT worker_id, fence FROM leases WHERE effect_id = 'deploy-1'"
        ).fetchone() == ("worker-b", current.fence)
    finally:
        connection.close()
    assert observed_watermark(journal_path) == denied_at.isoformat(
        timespec="microseconds"
    )
    journal.close()

    clock.now -= timedelta(seconds=5)
    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(ClockRollback):
            reopened.acquire_attempt(
                "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
            )
    finally:
        reopened.close()


def test_effect_conflict_denial_commits_watermark_without_state_mutation(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if an invalid effect edge lost its later clock observation."""
    journal = Journal.open(journal_path, clock=clock)
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    clock.advance(timedelta(seconds=10))
    denied_at = clock.now

    with pytest.raises(EffectConflict):
        journal.record_effect(
            "deploy-1", lease.fence, EffectState.COMPLETED, "evidence://skipped"
        )

    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    assert observed_watermark(journal_path) == denied_at.isoformat(
        timespec="microseconds"
    )
    journal.close()

    clock.now -= timedelta(seconds=5)
    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(ClockRollback):
            reopened.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
        assert reopened.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    finally:
        reopened.close()


def test_reconciliation_conflict_denial_commits_watermark_without_second_audit(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if contradictory probe denial rolled back its observed time."""
    journal = Journal.open(journal_path, clock=clock)
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    committed = journal.record_reconciliation(
        "deploy-1", lease.fence, ReconciliationOutcome.UNKNOWN, "probe://unknown"
    )
    clock.advance(timedelta(seconds=10))
    denied_at = clock.now

    with pytest.raises(EffectConflict):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.OBSERVED_ABSENT,
            "probe://absent",
        )

    assert journal.list_reconciliations("deploy-1") == (committed,)
    assert observed_watermark(journal_path) == denied_at.isoformat(
        timespec="microseconds"
    )
    journal.close()

    clock.now -= timedelta(seconds=5)
    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(ClockRollback):
            reopened.record_reconciliation(
                "deploy-1",
                lease.fence,
                ReconciliationOutcome.UNKNOWN,
                "probe://unknown",
            )
        assert reopened.list_reconciliations("deploy-1") == (committed,)
    finally:
        reopened.close()


def test_invalid_reconciliation_state_denial_commits_watermark_without_audit(
    journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if invalid-state denial lost time or partially wrote an audit."""
    journal = Journal.open(journal_path, clock=clock)
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    clock.advance(timedelta(seconds=10))
    denied_at = clock.now

    with pytest.raises(EffectConflict):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.UNKNOWN,
            "probe://invalid-state",
        )

    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    assert journal.list_reconciliations("deploy-1") == ()
    assert observed_watermark(journal_path) == denied_at.isoformat(
        timespec="microseconds"
    )
    journal.close()

    clock.now -= timedelta(seconds=5)
    reopened = Journal.open(journal_path, clock=clock)
    try:
        with pytest.raises(ClockRollback):
            reopened.record_reconciliation(
                "deploy-1",
                lease.fence,
                ReconciliationOutcome.UNKNOWN,
                "probe://invalid-state",
            )
        assert reopened.list_reconciliations("deploy-1") == ()
    finally:
        reopened.close()


def test_exact_lease_expiry_is_available_for_takeover(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if now equal to expires_at remained incorrectly leased."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    clock.advance(timedelta(seconds=1))

    takeover = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )

    assert takeover.fence > first.fence


def test_negative_lease_ttl_is_rejected_without_creating_authority(
    journal: Journal,
) -> None:
    """Would fail if a negative TTL could manufacture immediately stale authority."""
    seed_effect(journal)

    with pytest.raises(ValueError, match="non-negative"):
        journal.acquire_attempt(
            "run-1", "deploy-1", "worker-a", timedelta(microseconds=-1)
        )


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


@pytest.mark.parametrize("fence_selector", ["old", "invented"])
def test_terminal_replay_rejects_any_fence_other_than_committing_fence(
    journal: Journal, fence_selector: str
) -> None:
    """Would fail if exact evidence let an old or invented fence bypass authority."""
    seed_effect(journal)
    old = journal.acquire_attempt("run-1", "deploy-1", "worker-a", timedelta(seconds=0))
    committed = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", committed.fence, EffectState.STARTED, None)
    journal.record_effect(
        "deploy-1", committed.fence, EffectState.COMPLETED, "evidence://receipt-1"
    )
    supplied_fence = old.fence if fence_selector == "old" else committed.fence + 100

    with pytest.raises(StaleFence):
        journal.record_effect(
            "deploy-1", supplied_fence, EffectState.COMPLETED, "evidence://receipt-1"
        )


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
        journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.UNKNOWN,
            "probe://inconclusive",
        )

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


def test_observed_completed_reconciliation_requires_and_immutably_stores_evidence(
    journal: Journal,
) -> None:
    """Would fail if a completed probe could omit or later rewrite its receipt."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)

    with pytest.raises(EffectConflict):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.OBSERVED_COMPLETED,
            None,
        )

    committed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.OBSERVED_COMPLETED,
        "probe://completed-receipt",
    )
    assert journal.get_effect("run-1", "deploy-1").state is EffectState.COMPLETED
    assert journal.list_reconciliations("deploy-1")[0].outcome is (
        ReconciliationOutcome.OBSERVED_COMPLETED
    )
    assert (
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.OBSERVED_COMPLETED,
            "probe://completed-receipt",
        )
        == committed
    )

    with pytest.raises(EffectConflict):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.OBSERVED_COMPLETED,
            "probe://different-receipt",
        )


def test_observed_absent_reconciliation_preserves_audit_and_requires_new_fence(
    journal: Journal,
) -> None:
    """Would fail if a trusted absence probe erased history or reused its old fence."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://absent-receipt",
    )

    retry = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )

    assert retry.dispatch_allowed is True
    assert retry.fence > first.fence
    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    assert [item.evidence_ref for item in journal.list_reconciliations("deploy-1")] == [
        "probe://absent-receipt"
    ]


def test_unknown_reconciliation_blocks_dispatch_and_remains_auditable(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if an inconclusive probe could authorize another dispatch."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://timeout",
    )
    clock.advance(timedelta(seconds=2))

    retry_probe = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )

    assert retry_probe.dispatch_allowed is False
    assert journal.get_effect("run-1", "deploy-1").state is EffectState.RECONCILED
    assert journal.list_reconciliations("deploy-1")[0].outcome is (
        ReconciliationOutcome.UNKNOWN
    )


def test_unknown_reconciliation_lost_ack_replay_survives_expired_lease(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if replay consulted the now-terminal effect before its audit row."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    committed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://timeout",
    )
    clock.advance(timedelta(seconds=2))

    replayed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://timeout",
    )

    assert replayed == committed
    assert journal.list_reconciliations("deploy-1") == (committed,)


def test_absent_reconciliation_lost_ack_replay_survives_state_change(
    journal: Journal,
) -> None:
    """Would fail if an absent ACK replay were rejected after restoring intent."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    committed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://absent-receipt",
    )

    replayed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://absent-receipt",
    )

    assert replayed == committed
    assert journal.list_reconciliations("deploy-1") == (committed,)


def test_conflicting_reconciliation_lost_ack_replay_is_rejected(
    journal: Journal,
) -> None:
    """Would fail if one fence could append contradictory probe conclusions."""
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    committed = journal.record_reconciliation(
        "deploy-1",
        lease.fence,
        ReconciliationOutcome.UNKNOWN,
        "probe://timeout",
    )

    with pytest.raises(EffectConflict, match="conflicts with durable reconciliation"):
        journal.record_reconciliation(
            "deploy-1",
            lease.fence,
            ReconciliationOutcome.OBSERVED_ABSENT,
            "probe://absent-receipt",
        )

    assert journal.list_reconciliations("deploy-1") == (committed,)


def test_old_absent_ack_replay_after_new_fence_has_no_side_effect(
    journal: Journal,
) -> None:
    """Would fail if old ACK replay changed the newly fenced retry authority."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(minutes=1)
    )
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    committed = journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://absent-receipt",
    )
    retry = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
    )

    replayed = journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://absent-receipt",
    )

    assert replayed == committed
    assert retry.fence > first.fence
    assert (
        journal.acquire_attempt(
            "run-1", "deploy-1", "worker-b", timedelta(minutes=1)
        ).fence
        == retry.fence
    )
    assert journal.get_effect("run-1", "deploy-1").state is EffectState.INTENT
    assert journal.list_reconciliations("deploy-1") == (committed,)


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


def test_prepared_effect_durably_authorizes_commit_before_completion(
    tmp_path: Path,
) -> None:
    """Would fail if a host mutation had no durable write-ahead authorization."""
    journal = Journal.open(tmp_path / "prepared.sqlite3")
    seed_effect(journal)
    lease = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    stage_ref = "effect-stage://sha256/" + "a" * 64

    journal.record_effect("deploy-1", lease.fence, EffectState.STARTED, None)
    journal.record_effect("deploy-1", lease.fence, "prepared", stage_ref)

    prepared = journal.get_effect("run-1", "deploy-1")
    assert prepared is not None
    assert prepared.state.value == "prepared"
    assert prepared.evidence_ref == stage_ref
    assert not journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    ).dispatch_allowed

    journal.record_effect("deploy-1", lease.fence, EffectState.COMPLETED, stage_ref)
    completed = journal.get_effect("run-1", "deploy-1")
    assert completed is not None
    assert completed.state is EffectState.COMPLETED
    assert completed.evidence_ref == stage_ref
    journal.close()


def test_prepared_stage_can_only_be_adopted_by_new_live_fence(
    tmp_path: Path, clock: MutableClock
) -> None:
    """Would fail if an expired fence could apply or a retry lost its stage."""
    journal = Journal.open(tmp_path / "adopt.sqlite3", clock=clock)
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    prior = "effect-stage://sha256/" + "a" * 64
    adopted = "effect-stage://sha256/" + "b" * 64
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    journal.record_effect("deploy-1", first.fence, EffectState.PREPARED, prior)
    journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://host-before-manifest",
    )
    clock.advance(timedelta(seconds=2))
    second = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )

    assert second.fence > first.fence
    assert second.dispatch_allowed is False
    with pytest.raises(StaleFence):
        journal.adopt_prepared("deploy-1", first.fence, prior, adopted)

    journal.adopt_prepared("deploy-1", second.fence, prior, adopted)
    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.PREPARED
    assert effect.evidence_ref == adopted
    journal.record_effect("deploy-1", second.fence, EffectState.COMPLETED, adopted)
    journal.close()


def test_invalid_run_transition_does_not_append_event(journal: Journal) -> None:
    """Would fail if state changed before the lifecycle transition was validated."""
    journal.transition(request())

    with pytest.raises(InvalidTransition):
        journal.transition(request(expected_revision=1, event=RunEvent.ACCEPT))

    assert journal.get_run("run-1").state is RunState.DISCOVERY
    assert len(journal.list_events("run-1")) == 1


def test_begin_dispatch_reanchors_lease_from_actual_start(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if runtime authority were anchored before durable dispatch."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    admission_expires_at = clock.now + timedelta(seconds=30)
    clock.advance(timedelta(seconds=5))

    authority = journal.begin_dispatch(
        run_id="run-1",
        expected_revision=1,
        expected_state=RunState.DISCOVERY,
        effect_id="deploy-1",
        worker_id="worker-a",
        fence=reservation.fence,
        grant_id="a" * 64,
        admission_expires_at=admission_expires_at,
        worker_timeout=timedelta(seconds=30),
        termination_budget=timedelta(seconds=4),
        commit_budget=timedelta(seconds=29),
    )

    assert isinstance(authority, ExecutionAuthority)
    assert authority.started_at == datetime(2026, 8, 11, 12, 0, 5, tzinfo=UTC)
    assert authority.worker_deadline == datetime(2026, 8, 11, 12, 0, 35, tzinfo=UTC)
    assert authority.commit_deadline == datetime(2026, 8, 11, 12, 1, 8, tzinfo=UTC)
    assert authority.lease_expires_at == authority.commit_deadline
    assert authority.fence == reservation.fence
    assert authority.grant_id == "a" * 64
    assert authority.verify_digest()
    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.STARTED


def test_begin_dispatch_expired_admission_preserves_intent(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if expired admission crossed the durable dispatch boundary."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    admission_expires_at = clock.now + timedelta(seconds=30)
    clock.advance(timedelta(seconds=30))

    with pytest.raises(AdmissionExpired):
        journal.begin_dispatch(
            run_id="run-1",
            expected_revision=1,
            expected_state=RunState.DISCOVERY,
            effect_id="deploy-1",
            worker_id="worker-a",
            fence=reservation.fence,
            grant_id="a" * 64,
            admission_expires_at=admission_expires_at,
            worker_timeout=timedelta(seconds=30),
            termination_budget=timedelta(seconds=4),
            commit_budget=timedelta(seconds=29),
        )

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.INTENT
    assert len(journal.list_events("run-1")) == 1


@pytest.mark.parametrize(
    ("worker_id", "fence_offset"),
    [("worker-b", 0), ("worker-a", 1)],
)
def test_begin_dispatch_wrong_owner_or_fence_preserves_reservation(
    journal: Journal,
    journal_path: Path,
    clock: MutableClock,
    worker_id: str,
    fence_offset: int,
) -> None:
    """Would fail if a mismatched reservation could re-anchor an attempt lease."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    original_lease = lease_row(journal_path)
    admission_expires_at = clock.now + timedelta(seconds=30)

    with pytest.raises(StaleFence):
        journal.begin_dispatch(
            run_id="run-1",
            expected_revision=1,
            expected_state=RunState.DISCOVERY,
            effect_id="deploy-1",
            worker_id=worker_id,
            fence=reservation.fence + fence_offset,
            grant_id="a" * 64,
            admission_expires_at=admission_expires_at,
            worker_timeout=timedelta(seconds=30),
            termination_budget=timedelta(seconds=4),
            commit_budget=timedelta(seconds=29),
        )

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.INTENT
    assert lease_row(journal_path) == original_lease


def test_begin_dispatch_replay_requires_reconciliation(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if a durable STARTED effect could launch a second worker."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    admission_expires_at = clock.now + timedelta(seconds=30)
    arguments = {
        "run_id": "run-1",
        "expected_revision": 1,
        "expected_state": RunState.DISCOVERY,
        "effect_id": "deploy-1",
        "worker_id": "worker-a",
        "fence": reservation.fence,
        "grant_id": "a" * 64,
        "admission_expires_at": admission_expires_at,
        "worker_timeout": timedelta(seconds=30),
        "termination_budget": timedelta(seconds=4),
        "commit_budget": timedelta(seconds=29),
    }

    journal.begin_dispatch(**arguments)

    with pytest.raises(ReconciliationRequired):
        journal.begin_dispatch(**arguments)

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.STARTED


@pytest.mark.parametrize(
    ("expected_revision", "expected_state"),
    [(2, RunState.DISCOVERY), (1, RunState.REQUIREMENTS)],
)
def test_begin_dispatch_run_revision_and_state_are_atomic_guards(
    journal: Journal,
    clock: MutableClock,
    expected_revision: int,
    expected_state: RunState,
) -> None:
    """Would fail if dispatch accepted stale run lifecycle authority."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    admission_expires_at = clock.now + timedelta(seconds=30)

    with pytest.raises(RevisionConflict):
        journal.begin_dispatch(
            run_id="run-1",
            expected_revision=expected_revision,
            expected_state=expected_state,
            effect_id="deploy-1",
            worker_id="worker-a",
            fence=reservation.fence,
            grant_id="a" * 64,
            admission_expires_at=admission_expires_at,
            worker_timeout=timedelta(seconds=30),
            termination_budget=timedelta(seconds=4),
            commit_budget=timedelta(seconds=29),
        )

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.INTENT


def test_begin_dispatch_clock_rollback_preserves_intent(
    journal: Journal, clock: MutableClock
) -> None:
    """Would fail if rollback could revive dispatch authority."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    admission_expires_at = clock.now + timedelta(seconds=30)
    clock.now = datetime(2026, 8, 11, 11, 59, 59, tzinfo=UTC)

    with pytest.raises(ClockRollback):
        journal.begin_dispatch(
            run_id="run-1",
            expected_revision=1,
            expected_state=RunState.DISCOVERY,
            effect_id="deploy-1",
            worker_id="worker-a",
            fence=reservation.fence,
            grant_id="a" * 64,
            admission_expires_at=admission_expires_at,
            worker_timeout=timedelta(seconds=30),
            termination_budget=timedelta(seconds=4),
            commit_budget=timedelta(seconds=29),
        )

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.INTENT


def test_begin_dispatch_lease_update_failure_rolls_back_started(
    journal: Journal, journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if a lease write failure left STARTED committed alone."""
    seed_effect(journal)
    reservation = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    original_lease = lease_row(journal_path)
    admission_expires_at = clock.now + timedelta(seconds=30)
    journal._connection.execute(
        "CREATE TRIGGER test_same_fence_lease_update_failure "
        "BEFORE UPDATE ON leases "
        "WHEN NEW.fence = OLD.fence AND NEW.expires_at != OLD.expires_at "
        "BEGIN SELECT RAISE(ABORT, 'test lease expiry failure'); END"
    )

    try:
        with pytest.raises(JournalStorageError):
            journal.begin_dispatch(
                run_id="run-1",
                expected_revision=1,
                expected_state=RunState.DISCOVERY,
                effect_id="deploy-1",
                worker_id="worker-a",
                fence=reservation.fence,
                grant_id="a" * 64,
                admission_expires_at=admission_expires_at,
                worker_timeout=timedelta(seconds=30),
                termination_budget=timedelta(seconds=4),
                commit_budget=timedelta(seconds=29),
            )
    finally:
        journal._connection.execute("DROP TRIGGER test_same_fence_lease_update_failure")

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.INTENT
    assert lease_row(journal_path) == original_lease


def test_begin_prepared_commit_anchors_only_commit_budget(
    journal: Journal, journal_path: Path, clock: MutableClock
) -> None:
    """Would fail if adopting a stage received another worker execution window."""
    seed_effect(journal)
    first = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=1)
    )
    prior = "effect-stage://sha256/" + "a" * 64
    adopted = "effect-stage://sha256/" + "b" * 64
    journal.record_effect("deploy-1", first.fence, EffectState.STARTED, None)
    journal.record_effect("deploy-1", first.fence, EffectState.PREPARED, prior)
    journal.record_reconciliation(
        "deploy-1",
        first.fence,
        ReconciliationOutcome.OBSERVED_ABSENT,
        "probe://host-before-manifest",
    )
    clock.advance(timedelta(seconds=2))
    second = journal.acquire_attempt(
        "run-1", "deploy-1", "worker-a", timedelta(seconds=30)
    )
    journal.adopt_prepared("deploy-1", second.fence, prior, adopted)
    admission_expires_at = clock.now + timedelta(seconds=30)

    authority = journal.begin_prepared_commit(
        run_id="run-1",
        expected_revision=1,
        expected_state=RunState.DISCOVERY,
        effect_id="deploy-1",
        worker_id="worker-a",
        fence=second.fence,
        grant_id="b" * 64,
        admission_expires_at=admission_expires_at,
        expected_evidence_ref=adopted,
        commit_budget=timedelta(seconds=29),
    )

    effect = journal.get_effect("run-1", "deploy-1")
    assert effect is not None
    assert effect.state is EffectState.PREPARED
    assert authority.worker_deadline == authority.started_at
    assert authority.commit_deadline == authority.started_at + timedelta(seconds=29)
    assert lease_row(journal_path)[1] == second.fence
