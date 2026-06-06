"""Generate position signals through registered timer builders.

CALLING SPEC:
    signals = build_signals(
        index_daily=pd.DataFrame,
        trade_dates=list[str],
        timer_cfg=TimerConfigV1,
    ) -> pd.DataFrame
        Returns DataFrame with columns [trade_date, position].

SIDE EFFECTS:
    Depends on the selected timer builder. The orchestrator entrypoint itself
    does not read or write files.
"""

from __future__ import annotations

import pandas as pd

from src.schemas.strategy import TimerConfigV1
from src.timer.builders import FEATURE_COLS, training_mask_for_cutoff
from src.timer.registry import get_timer_builder
from src.timer.signal import align_signals_to_calendar

# Backward-compatible names for existing tests and diagnostics.
_FEATURE_COLS = FEATURE_COLS
_training_mask_for_cutoff = training_mask_for_cutoff


def build_signals(
    index_daily: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1 | None = None,
) -> pd.DataFrame:
    """Build strategy timer signals while keeping the public API stable."""
    if timer_cfg is None:
        timer_cfg = TimerConfigV1()

    requested_dates = [str(d) for d in trade_dates]
    builder = get_timer_builder(str(timer_cfg.mode))
    raw = builder(index_daily, requested_dates, timer_cfg)
    return _normalize_timer_output(raw, requested_dates)


def _normalize_timer_output(signals: pd.DataFrame, trade_dates: list[str]) -> pd.DataFrame:
    """Return one clipped numeric position for every requested trade date."""
    if signals is None:
        signals = pd.DataFrame(columns=["trade_date", "position"])
    missing = {"trade_date", "position"} - set(signals.columns)
    if missing:
        missing_cols = ", ".join(sorted(missing))
        raise ValueError(f"Timer builder output missing required column(s): {missing_cols}")

    raw = signals[["trade_date", "position"]].copy()
    raw["position"] = pd.to_numeric(raw["position"], errors="coerce")
    raw = raw.dropna(subset=["position"])
    aligned = align_signals_to_calendar(raw, trade_dates, default_position=0.0)
    aligned["position"] = aligned["position"].clip(lower=0.0, upper=1.0)
    return aligned
