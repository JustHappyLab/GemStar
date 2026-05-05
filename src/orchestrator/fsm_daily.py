"""Daily run finite state machine.

CALLING SPEC:
    daily_states() -> list[str]
        Returns all valid daily run states.

    DailyFSM(db_path, run_id)
        .current()  -> str  (current state)
        .transition(to) -> None  (validates and records the transition)
        .is_terminal() -> bool
        .is_degraded() -> bool

SIDE EFFECTS:
    Writes to state.db steps table via record_step().
"""

import sqlite3
from enum import Enum

from src.orchestrator.run_manifest import record_step


class DailyState(str, Enum):
    INITIALIZED = "initialized"
    COLLECTING = "collecting"
    QUALITY_CHECKING = "quality_checking"
    FACTOR_MONITORING = "factor_monitoring"
    STRATEGY_IDEATION = "strategy_ideation"
    STRATEGY_VALIDATION = "strategy_validation"
    BACKTESTING = "backtesting"
    JUDGING = "judging"
    LEADERBOARD_BUILDING = "leaderboard_building"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    DEGRADED = "degraded"
    MANUAL_ATTENTION = "manual_attention"


_ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    DailyState.INITIALIZED: [DailyState.COLLECTING],
    DailyState.COLLECTING: [DailyState.QUALITY_CHECKING, DailyState.FAILED],
    DailyState.QUALITY_CHECKING: [
        DailyState.FACTOR_MONITORING,
        DailyState.DEGRADED,
        DailyState.MANUAL_ATTENTION,
    ],
    DailyState.FACTOR_MONITORING: [DailyState.STRATEGY_IDEATION, DailyState.FAILED],
    DailyState.STRATEGY_IDEATION: [DailyState.STRATEGY_VALIDATION, DailyState.FAILED],
    DailyState.STRATEGY_VALIDATION: [DailyState.BACKTESTING, DailyState.REPORTING],
    DailyState.BACKTESTING: [DailyState.JUDGING, DailyState.FAILED],
    DailyState.JUDGING: [DailyState.LEADERBOARD_BUILDING],
    DailyState.LEADERBOARD_BUILDING: [DailyState.REPORTING],
    DailyState.REPORTING: [DailyState.COMPLETED, DailyState.DEGRADED],
    # terminal
    DailyState.COMPLETED: [],
    DailyState.FAILED: [],
    DailyState.DEGRADED: [
        DailyState.FACTOR_MONITORING,
        DailyState.REPORTING,
        DailyState.FAILED,
    ],  # degraded can continue the normal pipeline or report early
    DailyState.MANUAL_ATTENTION: [],
}


def daily_states() -> list[str]:
    return [s.value for s in DailyState]


def is_terminal(state: str) -> bool:
    return state in (DailyState.COMPLETED, DailyState.FAILED, DailyState.MANUAL_ATTENTION)


def is_degraded(state: str) -> bool:
    return state == DailyState.DEGRADED


class DailyFSM:
    """State machine for a single daily run."""

    def __init__(self, run_id: str, db_path: str = "state.db"):
        self.run_id = run_id
        self._db_path = db_path
        self._state = DailyState.INITIALIZED

    def current(self) -> str:
        return self._state.value

    def transition(self, to: str) -> None:
        target = DailyState(to)
        allowed = _ALLOWED_TRANSITIONS.get(self._state, [])
        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {self._state.value} -> {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self._state = target
        record_step(
            run_id=self.run_id,
            step_id=target.value,
            role="orchestrator",
            status="started",
            db_path=self._db_path,
        )

    def is_terminal(self) -> bool:
        return is_terminal(self._state.value)

    def is_degraded(self) -> bool:
        return is_degraded(self._state.value)
