"""Normalize local market data into live radar snapshots.

CALLING SPEC:
    snapshots = snapshots_from_daily_df(
        daily_df=pd.DataFrame,
        trade_date=str | None,
        source=str,
    ) -> list[MarketSnapshotV1]

    snapshots = snapshots_from_file(
        path=Path,
        trade_date=str | None,
        source=str,
    ) -> list[MarketSnapshotV1]

SIDE EFFECTS:
    snapshots_from_file reads a local CSV or Parquet file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.schemas.live import MarketSnapshotV1


def snapshots_from_daily_df(
    daily_df: pd.DataFrame,
    trade_date: str | None = None,
    source: str = "daily_cache",
) -> list[MarketSnapshotV1]:
    """Convert daily OHLCV rows into normalized market snapshots."""
    if daily_df.empty:
        return []
    _require_columns(daily_df, ["ts_code", "trade_date", "close"])

    df = daily_df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    target_date = trade_date or str(df["trade_date"].max())
    day = df[df["trade_date"] == target_date].copy()
    if day.empty:
        return []

    snapshots: list[MarketSnapshotV1] = []
    for _, row in day.sort_values("ts_code").iterrows():
        last_price = _positive_float_or_none(row.get("close"))
        if last_price is None:
            continue
        pre_close = _positive_float_or_none(row.get("pre_close"))
        limit_up, limit_down = _limit_flags(last_price, pre_close)
        snapshots.append(
            MarketSnapshotV1(
                ts_code=str(row["ts_code"]),
                trade_date=target_date,
                last_price=last_price,
                open=_positive_float_or_none(row.get("open")),
                high=_positive_float_or_none(row.get("high")),
                low=_positive_float_or_none(row.get("low")),
                pre_close=pre_close,
                volume=_non_negative_float(row.get("vol", row.get("volume", 0.0))),
                limit_up=limit_up,
                limit_down=limit_down,
                source=source,
            )
        )
    return snapshots


def snapshots_from_file(
    path: str | Path,
    trade_date: str | None = None,
    source: str = "daily_cache",
) -> list[MarketSnapshotV1]:
    """Read local CSV/Parquet market data and return normalized snapshots."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    elif p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
    else:
        raise ValueError(f"Unsupported snapshot file type: {p.suffix}")
    return snapshots_from_daily_df(df, trade_date=trade_date, source=source)


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required snapshot columns: {missing}")


def _positive_float_or_none(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    v = float(value)
    if v <= 0:
        return None
    return v


def _non_negative_float(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return max(0.0, float(value))


def _limit_flags(last_price: float, pre_close: float | None) -> tuple[bool, bool]:
    if pre_close is None:
        return False, False
    pct = (last_price - pre_close) / pre_close
    tolerance = 0.005
    limit = 0.20
    hit = abs(abs(pct) - limit) < tolerance
    return pct > 0 and hit, pct < 0 and hit
