"""Timer builder registry.

CALLING SPEC:
    builder = get_timer_builder(mode)
    builder(index_daily, trade_dates, timer_cfg) -> pd.DataFrame

SIDE EFFECTS:
    None.
"""

from __future__ import annotations

from src.timer.builders import (
    TimerBuilder,
    build_full_signals,
    build_lstm_signals,
    build_ma_signals,
)


TIMER_REGISTRY: dict[str, TimerBuilder] = {
    "full": build_full_signals,
    "ma": build_ma_signals,
    "lstm": build_lstm_signals,
}


def get_timer_builder(mode: str) -> TimerBuilder:
    """Return the builder registered for a timer mode."""
    key = str(mode)
    try:
        return TIMER_REGISTRY[key]
    except KeyError as exc:
        available = ", ".join(sorted(TIMER_REGISTRY))
        raise ValueError(f"Unsupported timer mode '{key}'. Available modes: {available}") from exc
