"""Incident finite state machine.

CALLING SPEC:
    IncidentFSM()
        .current()    -> str  (current state)
        .transition(to) -> None  (validates the transition)
        .is_terminal() -> bool

    Incident lifecycle:
        detected → classified → retrying | degraded | manual_attention |
                   engineering_task_created → resolved

SIDE EFFECTS:
    None — pure state machine.
"""

from enum import Enum


class IncidentState(str, Enum):
    DETECTED = "detected"
    CLASSIFIED = "classified"
    RETRYING = "retrying"
    DEGRADED = "degraded"
    MANUAL_ATTENTION = "manual_attention"
    ENGINEERING_TASK_CREATED = "engineering_task_created"
    RESOLVED = "resolved"


_ALLOWED_TRANSITIONS: dict[IncidentState, list[IncidentState]] = {
    IncidentState.DETECTED: [IncidentState.CLASSIFIED],
    IncidentState.CLASSIFIED: [
        IncidentState.RETRYING,
        IncidentState.DEGRADED,
        IncidentState.MANUAL_ATTENTION,
        IncidentState.ENGINEERING_TASK_CREATED,
        IncidentState.RESOLVED,
    ],
    IncidentState.RETRYING: [IncidentState.RESOLVED, IncidentState.CLASSIFIED],
    IncidentState.DEGRADED: [IncidentState.RESOLVED],
    IncidentState.MANUAL_ATTENTION: [
        IncidentState.RESOLVED,
        IncidentState.ENGINEERING_TASK_CREATED,
    ],
    IncidentState.ENGINEERING_TASK_CREATED: [IncidentState.RESOLVED],
    IncidentState.RESOLVED: [],
}


def incident_states() -> list[str]:
    return [s.value for s in IncidentState]


def is_terminal(state: str) -> bool:
    return state == IncidentState.RESOLVED


class IncidentFSM:
    """State machine for a single incident."""

    def __init__(self) -> None:
        self._state = IncidentState.DETECTED

    def current(self) -> str:
        return self._state.value

    def transition(self, to: str) -> None:
        target = IncidentState(to)
        allowed = _ALLOWED_TRANSITIONS.get(self._state, [])
        if target not in allowed:
            raise ValueError(
                f"Invalid incident transition: {self._state.value} -> {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self._state = target

    def is_terminal(self) -> bool:
        return is_terminal(self._state.value)
