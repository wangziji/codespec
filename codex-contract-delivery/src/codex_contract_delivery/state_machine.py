"""Explicit, bounded lifecycle transitions for governed delivery runs."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class RunState(str, Enum):
    NEW = "new"
    DISCOVERY = "discovery"
    REQUIREMENTS = "requirements"
    GATE_1 = "gate_1"
    DESIGN = "design"
    MODULES = "modules"
    GATE_2 = "gate_2"
    PLANNING = "planning"
    GATE_3 = "gate_3"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    TEST = "test"
    PRODUCTION_AUTHORIZATION = "production_authorization"
    PROD = "prod"
    ACCEPTANCE = "acceptance"
    COMPLETED = "completed"
    INCIDENT = "incident"
    CORRECTION = "correction"
    ROLLBACK = "rollback"
    SAFE_CHECKPOINT = "safe_checkpoint"


class RunEvent(str, Enum):
    DISCOVER = "DISCOVER"
    DRAFT_REQUIREMENTS = "DRAFT_REQUIREMENTS"
    APPROVE_GATE_1 = "APPROVE_GATE_1"
    DESIGN = "DESIGN"
    DEFINE_MODULES = "DEFINE_MODULES"
    APPROVE_GATE_2 = "APPROVE_GATE_2"
    PLAN = "PLAN"
    APPROVE_GATE_3 = "APPROVE_GATE_3"
    IMPLEMENT = "IMPLEMENT"
    VERIFY = "VERIFY"
    RELEASE_TEST = "RELEASE_TEST"
    REQUEST_PRODUCTION = "REQUEST_PRODUCTION"
    RELEASE_PRODUCTION = "RELEASE_PRODUCTION"
    ACCEPT = "ACCEPT"
    APPROVE_GATE_4 = "APPROVE_GATE_4"
    INVALIDATE_DEPENDENCY = "INVALIDATE_DEPENDENCY"
    RECORD_INCIDENT = "RECORD_INCIDENT"
    CORRECT = "CORRECT"
    ROLLBACK = "ROLLBACK"
    ENTER_SAFE_CHECKPOINT = "ENTER_SAFE_CHECKPOINT"


class InvalidTransition(ValueError):
    """A stable domain error for an absent or insufficiently proven edge."""


_FORWARD_TRANSITIONS = {
    (RunState.NEW, RunEvent.DISCOVER): RunState.DISCOVERY,
    (RunState.DISCOVERY, RunEvent.DRAFT_REQUIREMENTS): RunState.REQUIREMENTS,
    (RunState.REQUIREMENTS, RunEvent.APPROVE_GATE_1): RunState.GATE_1,
    (RunState.GATE_1, RunEvent.DESIGN): RunState.DESIGN,
    (RunState.DESIGN, RunEvent.DEFINE_MODULES): RunState.MODULES,
    (RunState.MODULES, RunEvent.APPROVE_GATE_2): RunState.GATE_2,
    (RunState.GATE_2, RunEvent.PLAN): RunState.PLANNING,
    (RunState.PLANNING, RunEvent.APPROVE_GATE_3): RunState.GATE_3,
    (RunState.GATE_3, RunEvent.IMPLEMENT): RunState.IMPLEMENTATION,
    (RunState.IMPLEMENTATION, RunEvent.VERIFY): RunState.VERIFICATION,
    (RunState.VERIFICATION, RunEvent.RELEASE_TEST): RunState.TEST,
    (RunState.TEST, RunEvent.REQUEST_PRODUCTION): RunState.PRODUCTION_AUTHORIZATION,
    (RunState.PRODUCTION_AUTHORIZATION, RunEvent.RELEASE_PRODUCTION): RunState.PROD,
    (RunState.PROD, RunEvent.ACCEPT): RunState.ACCEPTANCE,
    (RunState.ACCEPTANCE, RunEvent.APPROVE_GATE_4): RunState.COMPLETED,
}

_INVALIDATABLE_STATES = frozenset(
    state
    for state in RunState
    if state
    not in {
        RunState.NEW,
        RunState.DISCOVERY,
        RunState.COMPLETED,
        RunState.SAFE_CHECKPOINT,
        RunState.INCIDENT,
        RunState.ROLLBACK,
    }
)
_INCIDENT_ORIGINS = frozenset(
    {
        RunState.IMPLEMENTATION,
        RunState.VERIFICATION,
        RunState.TEST,
        RunState.PRODUCTION_AUTHORIZATION,
        RunState.PROD,
        RunState.ACCEPTANCE,
    }
)

_RECOVERY_TRANSITIONS = {
    **{
        (state, RunEvent.INVALIDATE_DEPENDENCY): RunState.SAFE_CHECKPOINT
        for state in _INVALIDATABLE_STATES
    },
    **{
        (state, RunEvent.RECORD_INCIDENT): RunState.INCIDENT
        for state in _INCIDENT_ORIGINS
    },
    (RunState.INCIDENT, RunEvent.CORRECT): RunState.CORRECTION,
    (RunState.INCIDENT, RunEvent.ROLLBACK): RunState.ROLLBACK,
    (RunState.CORRECTION, RunEvent.ROLLBACK): RunState.ROLLBACK,
    (RunState.CORRECTION, RunEvent.ENTER_SAFE_CHECKPOINT): RunState.SAFE_CHECKPOINT,
    (RunState.ROLLBACK, RunEvent.ENTER_SAFE_CHECKPOINT): RunState.SAFE_CHECKPOINT,
}

_TRANSITIONS = _FORWARD_TRANSITIONS | _RECOVERY_TRANSITIONS
_INCIDENT_EVENTS = frozenset(
    {
        RunEvent.RECORD_INCIDENT,
        RunEvent.CORRECT,
        RunEvent.ROLLBACK,
        RunEvent.ENTER_SAFE_CHECKPOINT,
    }
)


class StateMachine:
    """Resolve only enumerated lifecycle edges; there is no generic retry."""

    def allowed(self, state: RunState, event: RunEvent) -> bool:
        try:
            normalized_state = RunState(state)
            normalized_event = RunEvent(event)
        except ValueError:
            return False
        return (normalized_state, normalized_event) in _TRANSITIONS

    def next_state(
        self,
        state: RunState,
        event: RunEvent | str,
        context: Mapping[str, object],
    ) -> RunState:
        try:
            normalized_state = RunState(state)
            normalized_event = RunEvent(event)
        except (TypeError, ValueError) as error:
            raise InvalidTransition("unknown lifecycle state or event") from error

        target = _TRANSITIONS.get((normalized_state, normalized_event))
        if target is None:
            raise InvalidTransition(
                f"event {normalized_event.value} is not allowed from {normalized_state.value}"
            )
        if normalized_event is RunEvent.INVALIDATE_DEPENDENCY:
            self._require_record(
                context,
                "invalidated_dependency",
                required=("kind", "record_id"),
            )
        elif normalized_event in _INCIDENT_EVENTS:
            self._require_record(
                context,
                "incident_record",
                required=("incident_id", "severity"),
            )
        return target

    @staticmethod
    def _require_record(
        context: Mapping[str, object], key: str, *, required: tuple[str, ...]
    ) -> None:
        record = context.get(key)
        if not isinstance(record, Mapping) or any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in required
        ):
            raise InvalidTransition(
                f"{key} must be a structured record containing {', '.join(required)}"
            )
