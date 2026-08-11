from __future__ import annotations

import pytest
from codex_contract_delivery.state_machine import (
    InvalidTransition,
    RunEvent,
    RunState,
    StateMachine,
)

FORWARD_LIFECYCLE = (
    (RunState.NEW, RunEvent.DISCOVER, RunState.DISCOVERY),
    (RunState.DISCOVERY, RunEvent.DRAFT_REQUIREMENTS, RunState.REQUIREMENTS),
    (RunState.REQUIREMENTS, RunEvent.APPROVE_GATE_1, RunState.GATE_1),
    (RunState.GATE_1, RunEvent.DESIGN, RunState.DESIGN),
    (RunState.DESIGN, RunEvent.DEFINE_MODULES, RunState.MODULES),
    (RunState.MODULES, RunEvent.APPROVE_GATE_2, RunState.GATE_2),
    (RunState.GATE_2, RunEvent.PLAN, RunState.PLANNING),
    (RunState.PLANNING, RunEvent.APPROVE_GATE_3, RunState.GATE_3),
    (RunState.GATE_3, RunEvent.IMPLEMENT, RunState.IMPLEMENTATION),
    (RunState.IMPLEMENTATION, RunEvent.VERIFY, RunState.VERIFICATION),
    (RunState.VERIFICATION, RunEvent.RELEASE_TEST, RunState.TEST),
    (RunState.TEST, RunEvent.REQUEST_PRODUCTION, RunState.PRODUCTION_AUTHORIZATION),
    (RunState.PRODUCTION_AUTHORIZATION, RunEvent.RELEASE_PRODUCTION, RunState.PROD),
    (RunState.PROD, RunEvent.ACCEPT, RunState.ACCEPTANCE),
    (RunState.ACCEPTANCE, RunEvent.APPROVE_GATE_4, RunState.COMPLETED),
)


@pytest.mark.parametrize(("state", "event", "target"), FORWARD_LIFECYCLE)
def test_forward_lifecycle_is_explicit(
    state: RunState, event: RunEvent, target: RunState
) -> None:
    """Would fail if a required gate or release phase disappeared from the table."""
    machine = StateMachine()

    assert machine.allowed(state, event) is True
    assert machine.next_state(state, event, {}) is target


def test_generic_retry_or_arbitrary_backward_edge_does_not_exist() -> None:
    """Would fail if callers could bypass structured invalidation with a retry edge."""
    machine = StateMachine()

    assert "RETRY" not in RunEvent.__members__
    assert machine.allowed(RunState.VERIFICATION, RunEvent.IMPLEMENT) is False
    with pytest.raises(InvalidTransition):
        machine.next_state(RunState.VERIFICATION, RunEvent.IMPLEMENT, {})


@pytest.mark.parametrize(
    ("state", "event", "context", "target"),
    [
        (
            RunState.VERIFICATION,
            RunEvent.INVALIDATE_DEPENDENCY,
            {"invalidated_dependency": {"kind": "approval", "record_id": "gate-2"}},
            RunState.SAFE_CHECKPOINT,
        ),
        (
            RunState.PROD,
            RunEvent.RECORD_INCIDENT,
            {"incident_record": {"incident_id": "INC-1", "severity": "P1"}},
            RunState.INCIDENT,
        ),
        (
            RunState.INCIDENT,
            RunEvent.CORRECT,
            {"incident_record": {"incident_id": "INC-1", "severity": "P1"}},
            RunState.CORRECTION,
        ),
        (
            RunState.CORRECTION,
            RunEvent.ROLLBACK,
            {"incident_record": {"incident_id": "INC-1", "severity": "P1"}},
            RunState.ROLLBACK,
        ),
        (
            RunState.ROLLBACK,
            RunEvent.ENTER_SAFE_CHECKPOINT,
            {"incident_record": {"incident_id": "INC-1", "severity": "P1"}},
            RunState.SAFE_CHECKPOINT,
        ),
    ],
)
def test_structured_invalidation_and_incident_paths_enter_bounded_states(
    state: RunState,
    event: RunEvent,
    context: dict[str, object],
    target: RunState,
) -> None:
    """Would fail if the incident path ignored its provenance or escaped its fixed target."""
    assert StateMachine().next_state(state, event, context) is target


@pytest.mark.parametrize(
    ("state", "event", "context"),
    [
        (RunState.VERIFICATION, RunEvent.INVALIDATE_DEPENDENCY, {}),
        (RunState.PROD, RunEvent.RECORD_INCIDENT, {}),
        (RunState.INCIDENT, RunEvent.CORRECT, {"incident_record": "INC-1"}),
        (
            RunState.ROLLBACK,
            RunEvent.ENTER_SAFE_CHECKPOINT,
            {"incident_record": {"severity": "P1"}},
        ),
    ],
)
def test_backward_or_incident_edges_require_structured_provenance(
    state: RunState, event: RunEvent, context: dict[str, object]
) -> None:
    """Would fail if a bare label were enough to authorize rollback or checkpoint entry."""
    with pytest.raises(InvalidTransition):
        StateMachine().next_state(state, event, context)


def test_completed_and_safe_checkpoint_have_no_implicit_resume_edge() -> None:
    """Would fail if terminal or paused runs could resume without a new governed decision."""
    machine = StateMachine()

    assert all(not machine.allowed(RunState.COMPLETED, event) for event in RunEvent)
    assert all(
        not machine.allowed(RunState.SAFE_CHECKPOINT, event) for event in RunEvent
    )
