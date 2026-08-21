# Task 5 Dispatch Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anchor worker execution and commit authority at the durable `STARTED` transition so pre-dispatch work cannot consume a successful worker's commit reserve.

**Architecture:** Keep the immutable grant as dispatch admission and reuse the existing attempt row/fence. The journal atomically changes `INTENT` to `STARTED`, re-anchors the same-fence lease from its durable clock, and returns a derived `ExecutionAuthority`; broker commit checks use that lease rather than grant expiry.

**Tech Stack:** Python 3.12, SQLite WAL/STRICT tables, `BEGIN IMMEDIATE`, frozen dataclasses, pytest, Ruff, uv

**Spec:** `docs/superpowers/specs/2026-08-15-task5-dispatch-authority-design.md`

## Global Constraints

- The grant expiry determines whether dispatch may begin; it is not the runtime deadline.
- `Journal.begin_dispatch()` must record `STARTED` and re-anchor the lease in one `_authority_transaction()`.
- Reuse the existing `leases` row and fence. Current schema explicitly permits same-fence expiry updates; do not add a table or schema version.
- `begin_dispatch()` accepts only `INTENT`. A repeated call after `STARTED` requires reconciliation and cannot launch twice.
- The subprocess receives exactly policy `timeout_seconds`.
- Worker execution lease TTL is policy timeout + 2-second TERM + 2-second KILL + 29-second commit budget.
- After `STARTED`, temporal authority comes from the current journal lease. Grant expiry alone does not invalidate a live attempt.
- Workflow Release, policy, approval, run, resource, owner, or fence drift still denies commit.
- Do not weaken `PREPARED`, content-addressed staging, rollback, typed reconciliation, or explicit new-fence adoption.
- All deadline decisions use the journal durable clock watermark.
- Do not change Lima/Codex sandboxing, VM attestation, credentials, network policy, the 24 MiB snapshot bound, or Task 6.

## File Responsibilities

- `codex-contract-delivery/src/codex_contract_delivery/journal.py`: derived authority and atomic lease re-anchoring.
- `codex-contract-delivery/src/codex_contract_delivery/capabilities.py`: admission/binding validation split and dispatch integration.
- `codex-contract-delivery/src/codex_contract_delivery/worker.py`: result callback authority binding.
- `codex-contract-delivery/tests/unit/test_journal.py`: transaction, clock, fence, replay, and adoption evidence.
- `codex-contract-delivery/tests/unit/test_capabilities.py`: delayed-dispatch and grant/runtime separation evidence.
- `codex-contract-delivery/tests/unit/test_worker.py`: launcher callback binding.
- `codex-contract-delivery/tests/unit/test_vm_worker.py`: unchanged PREPARED/rollback/adoption regressions.
- `docs/superpowers/plans/2026-08-11-codex-contract-delivery.md`: parent-plan amendment pointer.

---

### Task 1: Add Atomic Journal Execution Authority

**Files:**
- Modify: `codex-contract-delivery/src/codex_contract_delivery/journal.py`
- Modify: `codex-contract-delivery/tests/unit/test_journal.py`

**Interfaces:**
- Consumes: `Journal.acquire_attempt() -> Lease`, `EffectState`, `RunState`, `_authority_transaction()`.
- Produces: `ExecutionAuthority`, `AdmissionExpired`, `Journal.begin_dispatch()`, `Journal.begin_prepared_commit()`.

- [ ] **Step 1: Write the primary failing start-time test**

Add `ExecutionAuthority` and `AdmissionExpired` imports, then add:

```python
def test_begin_dispatch_reanchors_lease_from_actual_start(
    journal: Journal, clock: MutableClock
) -> None:
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
```

- [ ] **Step 2: Add the remaining journal RED cases**

Use the existing real SQLite fixture for these exact cases:

| Test name | Setup/action | Required assertion |
|---|---|---|
| `test_begin_dispatch_expired_admission_preserves_intent` | reserve 30s, capture admission expiry, advance exactly 30s, call `begin_dispatch` | raises `AdmissionExpired`; effect remains `INTENT`; process boundary is never reached |
| `test_begin_dispatch_wrong_owner_or_fence_preserves_reservation` | parameterize wrong worker and `fence + 1` | raises `StaleFence`; effect remains `INTENT`; lease expiry is unchanged |
| `test_begin_dispatch_replay_requires_reconciliation` | call once successfully, then call again with identical values | second call raises `ReconciliationRequired`; effect remains `STARTED` |
| `test_begin_dispatch_run_revision_and_state_are_atomic_guards` | parameterize revision 2 and `RunState.REQUIREMENTS` | raises `RevisionConflict`; effect remains `INTENT` |
| `test_begin_dispatch_clock_rollback_preserves_intent` | reserve at 12:00, move `MutableClock.now` to 11:59:59, call | raises `ClockRollback`; effect remains `INTENT` |
| `test_begin_dispatch_lease_update_failure_rolls_back_started` | install a temporary SQLite trigger that raises before same-fence lease expiry update | raises `JournalStorageError`; effect remains `INTENT`; original expiry remains |

Every expected value must be a literal or captured pre-action value, not computed by the production authority helper.

- [ ] **Step 3: Run RED**

```bash
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests/unit/test_journal.py \
  -q -k 'begin_dispatch or begin_prepared_commit'
```

Expected: import/attribute failures for the missing authority and methods.

- [ ] **Step 4: Implement the boundary value**

Add near `Lease`:

```python
class AdmissionExpired(JournalError):
    """A grant expired before its attempt durably started."""


@dataclass(frozen=True)
class ExecutionAuthority:
    grant_id: str
    run_id: str
    effect_id: str
    worker_id: str
    fence: int
    started_at: datetime
    worker_deadline: datetime
    commit_deadline: datetime
    lease_expires_at: datetime
    authority_digest: str

    def _content(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "run_id": self.run_id,
            "effect_id": self.effect_id,
            "worker_id": self.worker_id,
            "fence": self.fence,
            "started_at": _format_time(self.started_at),
            "worker_deadline": _format_time(self.worker_deadline),
            "commit_deadline": _format_time(self.commit_deadline),
            "lease_expires_at": _format_time(self.lease_expires_at),
        }

    def verify_digest(self) -> bool:
        return self.authority_digest == canonical_digest(self._content())
```

Import `canonical_digest` from `.canonical`. Build the frozen object through a private helper that first creates the exact mapping above and then computes `authority_digest`; tests must not call that helper for expected values.

- [ ] **Step 5: Implement atomic `begin_dispatch`**

Use this exact signature:

```python
def begin_dispatch(
    self,
    *,
    run_id: str,
    expected_revision: int,
    expected_state: RunState,
    effect_id: str,
    worker_id: str,
    fence: int,
    grant_id: str,
    admission_expires_at: datetime,
    worker_timeout: timedelta,
    termination_budget: timedelta,
    commit_budget: timedelta,
) -> ExecutionAuthority:
```

Before opening the transaction, validate identifiers, timezone-aware admission expiry, positive worker timeout, and non-negative budgets. Inside one `_authority_transaction()`:

1. select the run, effect, and lease in one query;
2. require exact revision/state, `INTENT`, owner/fence, unexpired reservation, and `now < admission_expires_at`;
3. compute worker deadline and commit deadline from the transaction's `now`;
4. update `effects` from `INTENT` to `STARTED` with a row-count guard;
5. update only `expires_at` on the matching same-fence lease row with a row-count guard; and
6. return the derived authority after both writes succeed.

Do not call `record_effect(STARTED)`: that would split state and lease changes into different transactions. Preserve the current `leases_fence_must_advance` trigger definition, whose predicate permits same-fence expiry updates and rejects non-increasing changed fences.

- [ ] **Step 6: Add prepared-adoption RED and implementation**

Add `test_begin_prepared_commit_anchors_only_commit_budget`: create PREPARED under fence 1, record `OBSERVED_ABSENT`, advance beyond fence 1, acquire fence 2, call `adopt_prepared`, then call `begin_prepared_commit` with a 29-second budget. Assert effect stays PREPARED, `worker_deadline == started_at`, `commit_deadline == started_at + 29s`, and the lease row uses fence 2.

Implement this exact signature:

```python
def begin_prepared_commit(
    self,
    *,
    run_id: str,
    expected_revision: int,
    expected_state: RunState,
    effect_id: str,
    worker_id: str,
    fence: int,
    grant_id: str,
    admission_expires_at: datetime,
    expected_evidence_ref: str,
    commit_budget: timedelta,
) -> ExecutionAuthority:
```

It requires PREPARED plus exact evidence, owner, fence, live reservation, and admission expiry. It updates only lease expiry, returns an authority with `worker_deadline == started_at`, and never changes effect state or launches a worker.

- [ ] **Step 7: Run Task 1 GREEN and commit**

```bash
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests/unit/test_journal.py -q
uv run --project codex-contract-delivery --group test ruff check \
  codex-contract-delivery/src/codex_contract_delivery/journal.py \
  codex-contract-delivery/tests/unit/test_journal.py
uv run --project codex-contract-delivery --group test ruff format --check \
  codex-contract-delivery/src/codex_contract_delivery/journal.py \
  codex-contract-delivery/tests/unit/test_journal.py
git diff --check
git add codex-contract-delivery/src/codex_contract_delivery/journal.py \
  codex-contract-delivery/tests/unit/test_journal.py
git commit -m "feat(workflow): anchor authority at dispatch"
```

Expected: journal tests pass, schema stays v3, style/diff checks pass.

---

### Task 2: Integrate Execution Authority with Broker and Worker

**Files:**
- Modify: `codex-contract-delivery/src/codex_contract_delivery/capabilities.py`
- Modify: `codex-contract-delivery/src/codex_contract_delivery/worker.py`
- Modify: `codex-contract-delivery/tests/unit/test_capabilities.py`
- Modify: `codex-contract-delivery/tests/unit/test_worker.py`
- Modify: `codex-contract-delivery/tests/unit/test_vm_worker.py`
- Modify: `docs/superpowers/plans/2026-08-11-codex-contract-delivery.md`

**Interfaces:**
- Consumes: Task 1 `ExecutionAuthority`, `begin_dispatch`, `begin_prepared_commit`.
- Produces: `_validate_grant_bindings`, `_validate_grant_for_dispatch`, `_validate_execution_authority`, and three-argument result commit callbacks.

- [ ] **Step 1: Replace the delayed-success test and run RED**

Update the existing near-timeout test so authorization occurs at 12:00:00, the clock advances one second before `_dispatch`, the fake runner advances 29 seconds, and the committer receives `(prepared, authority, authority_check)`. Assert:

```python
assert observed_timeouts == [30]
assert authority.started_at == datetime(2026, 8, 11, 12, 0, 1, tzinfo=UTC)
assert authority.worker_deadline == datetime(2026, 8, 11, 12, 0, 31, tzinfo=UTC)
assert authority_check_seconds == [19.0]
assert result.status is DispatchStatus.COMPLETED
assert journal.get_effect("run-1", grant.effect_id).state is EffectState.COMPLETED
```

Add these exact behavior cases:

| Test name | Setup/action | Required assertion |
|---|---|---|
| `test_expired_grant_before_started_never_calls_runner` | advance exactly to `grant.expires_at`, call dispatch with a recording fake runner | raises `CapabilityDenied`; runner call list empty; effect `INTENT` |
| `test_grant_expiry_after_started_does_not_end_execution_authority` | delay 1s, runner advances 29s and returns success | commit succeeds although wall clock equals grant expiry; policy timeout passed to runner remains 30 |
| `test_live_run_drift_after_started_keeps_prepared` | fake runner performs legal `DRAFT_REQUIREMENTS` transition before returning success; committer calls authority check before mutation | result `RECONCILIATION_REQUIRED`; effect PREPARED with stage evidence |
| `test_tampered_execution_authority_is_denied` | `dataclasses.replace` a captured authority fence without recomputing digest | `_validate_execution_authority` raises `CapabilityDenied`; committer not called |

Run:

```bash
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests/unit/test_capabilities.py \
  codex-contract-delivery/tests/unit/test_worker.py \
  -q -k 'predispatch or grant_expiry or execution_authority or live_run_drift'
```

Expected: delayed success remains reconciliation-required and callback signature assertions fail before production changes.

- [ ] **Step 2: Split grant validation**

Create `_validate_grant_bindings` by moving the existing digest, issued-by-broker, Workflow Release, policy, live run revision/state, canonical resource, and write-scope checks out of `_validate_grant`. It must contain no grant-expiry, minimum-validity, or issue-time lease-expiry comparison.

Add:

```python
def _validate_grant_for_dispatch(self, grant: Grant) -> None:
    self._validate_grant_bindings(grant)
    if self._clock() >= grant.expires_at:
        self._deny(grant.request_digest, "grant-expired", "grant expired", grant=grant)
```

Add `_validate_execution_authority` to check `verify_digest`, grant ID, run/effect, worker, and fence. Remove the old minimum-validity parameter after all worker/adoption callers use journal authority.

For worker authorization, set admission grant expiry and reservation TTL to the policy timeout only. Remove issue-time `+ WORKER_COMMIT_AUTHORITY_SECONDS`; keep non-worker authorization semantics unchanged.

- [ ] **Step 3: Move worker `STARTED` to the launch boundary**

In `_dispatch`, validate grant admission and argv, then finish cwd, immutable executable, isolated HOME/Seatbelt command, child environment, and descriptor setup. Immediately before `_process_runner`, call:

```python
authority = self.journal.begin_dispatch(
    run_id=grant.run_id,
    expected_revision=grant.run_revision,
    expected_state=grant.run_state,
    effect_id=grant.effect_id,
    worker_id=grant.worker_id,
    fence=grant.fence,
    grant_id=grant.grant_id,
    admission_expires_at=grant.expires_at,
    worker_timeout=timedelta(seconds=grant.timeout_seconds),
    termination_budget=timedelta(seconds=4),
    commit_budget=timedelta(seconds=WORKER_COMMIT_AUTHORITY_SECONDS),
)
```

Use this only for `worker.analysis` and `worker.implementation`. Preserve the existing `record_effect(STARTED)` path for non-worker capabilities. Keep `_process_runner(timeout=grant.timeout_seconds)` unchanged and close all descriptors/temp directories if admission or `begin_dispatch` fails.

- [ ] **Step 4: Bind result commit and adoption**

Change result committer type to:

```python
Callable[[object, ExecutionAuthority, Callable[[float], None]], object]
```

Before result commit, validate the authority against the grant. The nested authority callback must run `_validate_grant_bindings(grant)` and then:

```python
self.journal.record_effect(
    grant.effect_id,
    grant.fence,
    EffectState.PREPARED,
    prepared_ref,
    minimum_lease_ttl=timedelta(seconds=required_seconds),
)
```

Update `WorkerLauncher.run`'s `commit_result` to receive the authority, require matching effect/fence, and pass only the existing authority-check callback to `backend.commit_export`. Do not expose the authority to the guest or VM protocol.

For prepared adoption: validate admission, durably adopt the stage, call `begin_prepared_commit` with the adopted evidence and 29-second commit budget, pass its authority to the committer, and use the same binding + lease-TTL callback. No worker process starts.

- [ ] **Step 5: Run focused and full GREEN**

```bash
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests/unit/test_capabilities.py \
  codex-contract-delivery/tests/unit/test_worker.py \
  codex-contract-delivery/tests/unit/test_vm_worker.py -q
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests -q
uv run --project codex-contract-delivery --group test pytest \
  codex-contract-delivery/tests/unit/test_schema.py \
  codex-contract-delivery/tests/unit/test_journal.py \
  codex-contract-delivery/tests/unit/test_capabilities.py -q
```

Required retained evidence: unchanged worker timeout; pre-start expiry; post-start grant expiry; live run/release/policy/resource/fence denial; timeout cancellation leaves STARTED; PREPARED lost ACK; mixed-state rollback; OBSERVED_ABSENT/new-fence adoption.

- [ ] **Step 6: Align parent plan, verify style, and commit**

Add directly below the parent Task 5 heading:

```markdown
> **Approved timing amendment:** Worker admission/runtime authority follows
> `docs/superpowers/specs/2026-08-15-task5-dispatch-authority-design.md` and
> `docs/superpowers/plans/2026-08-21-task5-dispatch-authority.md`. This supersedes
> Task 5 grant/lease timing only and does not widen worker capability.
```

Run:

```bash
uv run --project codex-contract-delivery --group test ruff check \
  codex-contract-delivery/src/codex_contract_delivery/{journal,capabilities,worker}.py \
  codex-contract-delivery/tests/unit/{test_journal,test_capabilities,test_worker,test_vm_worker}.py
uv run --project codex-contract-delivery --group test ruff format --check \
  codex-contract-delivery/src/codex_contract_delivery/{journal,capabilities,worker}.py \
  codex-contract-delivery/tests/unit/{test_journal,test_capabilities,test_worker,test_vm_worker}.py
git diff --check
git add codex-contract-delivery/src/codex_contract_delivery/capabilities.py \
  codex-contract-delivery/src/codex_contract_delivery/worker.py \
  codex-contract-delivery/tests/unit/test_capabilities.py \
  codex-contract-delivery/tests/unit/test_worker.py \
  codex-contract-delivery/tests/unit/test_vm_worker.py \
  docs/superpowers/plans/2026-08-11-codex-contract-delivery.md
git commit -m "fix(workflow): separate dispatch authority"
```

Expected: full Task 1-5 and schema/runtime parity pass; Ruff, format, and diff checks are clean. No paid Lima/model smoke is required because A1 changes only journal/broker timing authority.

## Completion Gate

1. Each task receives independent spec and quality review.
2. The delayed-dispatch counterexample is observed RED then GREEN.
3. No Critical or Important finding remains open.
4. The SDD ledger retains the historical Task 5 blocker and appends reviewed completion evidence.
5. Task 6 does not begin before Task 5 acceptance.
