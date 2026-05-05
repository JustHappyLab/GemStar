"""Generate position signals from LSTM timer model.

CALLING SPEC:
    signals = build_signals(
        index_daily=pd.DataFrame,
        trade_dates=list[str],
        timer_cfg=TimerConfigV1,
    ) -> pd.DataFrame
        Returns DataFrame with columns [trade_date, position].
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.schemas.strategy import TimerConfigV1
from src.timer.features import build_prediction_sequences, build_sequences_and_labels, compute_index_features
from src.timer.model import train_model
from src.timer.signal import align_signals_to_calendar, generate_signals

_FEATURE_COLS = [
    "ret_5", "ret_10", "ret_20", "ret_60",
    "ma_dev_5", "ma_dev_10", "ma_dev_20", "ma_dev_60",
    "vol_5", "vol_10", "vol_20", "vol_ratio_5_20",
    "rsi_14", "macd_diff", "macd_dea", "macd_hist", "adx_14",
]


def build_signals(
    index_daily: pd.DataFrame,
    trade_dates: list[str],
    timer_cfg: TimerConfigV1 | None = None,
) -> pd.DataFrame:
    """Train LSTM timer and generate position signals for the backtest window.

    Parameters
    ----------
    index_daily : DataFrame
        Index OHLCV with columns [trade_date, close, high, low, vol].
    trade_dates : list[str]
        Trading dates to generate signals for (YYYYMMDD).
    timer_cfg : TimerConfigV1, optional
        Timer hyperparameters. Uses defaults if None.

    Returns
    -------
    DataFrame with columns [trade_date, position].
    """
    if timer_cfg is None:
        timer_cfg = TimerConfigV1()

    if timer_cfg.mode == "full":
        return pd.DataFrame({"trade_date": trade_dates, "position": [1.0] * len(trade_dates)})

    if timer_cfg.mode == "ma":
        return _build_ma_signals(index_daily, trade_dates)

    features = compute_index_features(index_daily)
    if features.empty or len(features) < timer_cfg.seq_len + timer_cfg.horizon + 10:
        return pd.DataFrame({"trade_date": trade_dates, "position": [0.0] * len(trade_dates)})

    # Build training sequences
    X, y, dates_arr = build_sequences_and_labels(
        features, _FEATURE_COLS,
        seq_len=timer_cfg.seq_len,
        horizon=timer_cfg.horizon,
    )
    if len(X) < 100:
        return pd.DataFrame({"trade_date": trade_dates, "position": [0.0] * len(trade_dates)})

    # Train/val split (last 20% for validation)
    split = int(len(X) * 0.8)
    X_train, y_train = X[:split], y[:split]
    X_val, y_val = X[split:], y[split:]

    model, _ = train_model(
        X_train, y_train, X_val, y_val,
        epochs=timer_cfg.epochs,
        lr=timer_cfg.lr,
        patience=timer_cfg.patience,
        batch_size=timer_cfg.batch_size,
    )

    # Build prediction sequences for the target date range
    predict_start = trade_dates[0] if trade_dates else ""
    predict_end = trade_dates[-1] if trade_dates else ""
    X_pred, pred_dates = build_prediction_sequences(
        features, _FEATURE_COLS, predict_start, predict_end, timer_cfg.seq_len,
    )

    if len(X_pred) == 0:
        return pd.DataFrame({"trade_date": trade_dates, "position": [0.0] * len(trade_dates)})

    raw_signals = generate_signals(model, X_pred, pred_dates)
    return align_signals_to_calendar(raw_signals, trade_dates)


def _build_ma_signals(index_daily: pd.DataFrame, trade_dates: list[str], window: int = 20) -> pd.DataFrame:
    """Simple MA timer: invested when prior close is above its moving average."""
    if not trade_dates:
        return pd.DataFrame(columns=["trade_date", "position"])
    df = index_daily[["trade_date", "close"]].copy().sort_values("trade_date")
    df["trade_date"] = df["trade_date"].astype(str)
    df["ma"] = df["close"].rolling(window).mean()
    df["position"] = (df["close"].shift(1) > df["ma"].shift(1)).astype(float)
    raw = df[df["trade_date"].isin(trade_dates)][["trade_date", "position"]]
    return align_signals_to_calendar(raw, trade_dates)
