"""Concrete timer signal builders.

CALLING SPEC:
    builder(index_daily, trade_dates, timer_cfg) -> pd.DataFrame
        Returns columns [trade_date, position].

SIDE EFFECTS:
    LSTM builders train an in-memory PyTorch model and return generated
    signals. No files are read or written.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

from src.schemas.strategy import TimerConfigV1
from src.timer.features import (
    build_prediction_sequences,
    build_sequences_and_labels,
    compute_index_features,
)
from src.timer.model import train_model
from src.timer.signal import align_signals_to_calendar, generate_signals


class TimerBuilder(Protocol):
    """Callable interface for timer implementations."""

    def __call__(
        self,
        index_daily: pd.DataFrame,
        trade_dates: list[str],
        timer_cfg: TimerConfigV1,
    ) -> pd.DataFrame:
        """Build one position signal per requested trade date."""


FEATURE_COLS = [
    "ret_5", "ret_10", "ret_20", "ret_60",
    "ma_dev_5", "ma_dev_10", "ma_dev_20", "ma_dev_60",
    "vol_5", "vol_10", "vol_20", "vol_ratio_5_20",
    "rsi_14", "macd_diff", "macd_dea", "macd_hist", "adx_14",
]

MIN_LSTM_TRAIN_SAMPLES = 100


def build_full_signals(
    index_daily: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1,
) -> pd.DataFrame:
    """Always stay fully invested."""
    del index_daily, timer_cfg
    return pd.DataFrame({"trade_date": trade_dates, "position": [1.0] * len(trade_dates)})


def build_ma_signals(
    index_daily: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1,
    window: int = 20,
) -> pd.DataFrame:
    """Simple MA timer: invested when prior close is above its moving average."""
    del timer_cfg
    if not trade_dates:
        return pd.DataFrame(columns=["trade_date", "position"])
    df = index_daily[["trade_date", "close"]].copy().sort_values("trade_date")
    df["trade_date"] = df["trade_date"].astype(str)
    df["ma"] = df["close"].rolling(window).mean()
    df["position"] = (df["close"].shift(1) > df["ma"].shift(1)).astype(float)
    raw = df[df["trade_date"].isin(trade_dates)][["trade_date", "position"]]
    return align_signals_to_calendar(raw, trade_dates)


def build_lstm_signals(
    index_daily: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1,
) -> pd.DataFrame:
    """Train LSTM timer and generate position signals for the backtest window."""
    features = compute_index_features(index_daily.sort_values("trade_date"))
    if features.empty or len(features) < timer_cfg.seq_len + timer_cfg.horizon + 10:
        return pd.DataFrame({"trade_date": trade_dates, "position": [0.0] * len(trade_dates)})

    return build_walk_forward_lstm_signals(features, trade_dates, timer_cfg)


def build_walk_forward_lstm_signals(
    features: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1,
) -> pd.DataFrame:
    """Train LSTM only on labels observable before each retrain date."""
    if not trade_dates:
        return pd.DataFrame(columns=["trade_date", "position"])

    original_trade_dates = [str(d) for d in trade_dates]
    ordered_trade_dates = sorted(original_trade_dates)

    X, y, dates_arr = build_sequences_and_labels(
        features, FEATURE_COLS,
        seq_len=timer_cfg.seq_len,
        horizon=timer_cfg.horizon,
    )
    del dates_arr
    if len(X) < MIN_LSTM_TRAIN_SAMPLES:
        return pd.DataFrame({"trade_date": trade_dates, "position": [0.0] * len(trade_dates)})

    label_end_dates = label_end_dates_for_features(features, timer_cfg.seq_len, timer_cfg.horizon)
    raw_signals: list[pd.DataFrame] = []

    for retrain_date, segment_dates in retrain_segments(
        ordered_trade_dates, timer_cfg.retrain_months,
    ):
        train_mask = label_end_dates < retrain_date
        visible_count = int(train_mask.sum())
        if visible_count < MIN_LSTM_TRAIN_SAMPLES:
            continue

        X_visible = X[train_mask]
        y_visible = y[train_mask]
        split = int(len(X_visible) * 0.8)
        if split <= 0 or split >= len(X_visible):
            continue

        model, _ = train_model(
            X_visible[:split],
            y_visible[:split],
            X_visible[split:],
            y_visible[split:],
            epochs=timer_cfg.epochs,
            lr=timer_cfg.lr,
            patience=timer_cfg.patience,
            batch_size=timer_cfg.batch_size,
        )

        X_pred, pred_dates = build_prediction_sequences(
            features,
            FEATURE_COLS,
            segment_dates[0],
            segment_dates[-1],
            timer_cfg.seq_len,
        )
        if len(X_pred) > 0:
            raw_signals.append(generate_signals(model, X_pred, pred_dates))

    if raw_signals:
        raw = pd.concat(raw_signals, ignore_index=True)
    else:
        raw = pd.DataFrame(columns=["trade_date", "position"])
    return align_signals_to_calendar(raw, original_trade_dates)


def label_end_dates_for_features(features_df: pd.DataFrame, seq_len: int, horizon: int) -> np.ndarray:
    """Return the date on which each supervised label becomes knowable."""
    dates = features_df["trade_date"].astype(str).to_numpy()
    if len(dates) <= seq_len + horizon:
        return np.array([], dtype=object)
    return np.array(dates[seq_len + horizon:], dtype=object)


def training_mask_for_cutoff(
    features_df: pd.DataFrame,
    seq_len: int,
    horizon: int,
    cutoff_date: str,
) -> np.ndarray:
    """Samples are usable only if their forward-return label ends before cutoff."""
    return label_end_dates_for_features(features_df, seq_len, horizon) < str(cutoff_date)


def retrain_segments(
    trade_dates: list[str],
    retrain_months: int,
) -> list[tuple[str, list[str]]]:
    if not trade_dates:
        return []

    interval_months = max(1, int(retrain_months))
    starts: list[str] = []
    last_start: pd.Timestamp | None = None
    for trade_date in trade_dates:
        ts = pd.to_datetime(trade_date, format="%Y%m%d")
        if last_start is None or ts >= last_start + pd.DateOffset(months=interval_months):
            starts.append(trade_date)
            last_start = ts

    segments: list[tuple[str, list[str]]] = []
    for idx, start in enumerate(starts):
        next_start = starts[idx + 1] if idx + 1 < len(starts) else None
        segment_dates = [
            d for d in trade_dates
            if d >= start and (next_start is None or d < next_start)
        ]
        if segment_dates:
            segments.append((start, segment_dates))
    return segments
