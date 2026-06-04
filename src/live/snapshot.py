"""Normalize local market data into live radar snapshots.

CALLING SPEC:
    snapshots = snapshots_from_daily_df(
        daily_df=pd.DataFrame,
        trade_date=str | None,
        source=str,
    ) -> list[MarketSnapshotV1]

    snapshots = snapshots_from_realtime_df(
        realtime_df=pd.DataFrame,
        ts_codes=list[str] | None,
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

from datetime import datetime
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


def snapshots_from_realtime_df(
    realtime_df: pd.DataFrame,
    ts_codes: list[str] | None = None,
    trade_date: str | None = None,
    source: str = "tushare_realtime",
) -> list[MarketSnapshotV1]:
    """Convert Tushare realtime quote rows into normalized market snapshots."""
    if realtime_df is None or realtime_df.empty:
        return []
    _require_columns(realtime_df, ["price"])

    suffix_map = {_plain_code(code): code for code in (ts_codes or [])}
    target_codes = set(suffix_map.values())
    snapshots: list[MarketSnapshotV1] = []
    for _, row in realtime_df.copy().iterrows():
        ts_code = _realtime_ts_code(row, suffix_map)
        if not ts_code or (target_codes and ts_code not in target_codes):
            continue

        last_price = _positive_float_or_none(row.get("price"))
        if last_price is None:
            continue
        pre_close = _positive_float_or_none(row.get("pre_close"))
        limit_up, limit_down = _limit_flags(last_price, pre_close)
        snapshot_date = _realtime_trade_date(row, fallback=trade_date)
        snapshots.append(
            MarketSnapshotV1(
                ts_code=ts_code,
                trade_date=snapshot_date,
                timestamp=_realtime_timestamp(row, snapshot_date),
                last_price=last_price,
                open=_positive_float_or_none(row.get("open")),
                high=_positive_float_or_none(row.get("high")),
                low=_positive_float_or_none(row.get("low")),
                pre_close=pre_close,
                volume=_non_negative_float(row.get("volume", row.get("volumn", 0.0))),
                limit_up=limit_up,
                limit_down=limit_down,
                source=source,
            )
        )
    return snapshots


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


def _realtime_ts_code(row, suffix_map: dict[str, str]) -> str | None:
    for col in ("ts_code", "code", "symbol"):
        if col not in row or pd.isna(row.get(col)):
            continue
        raw = str(row.get(col)).strip()
        if not raw:
            continue
        if "." in raw:
            return raw.upper()
        plain = _plain_code(raw)
        if plain in suffix_map:
            return suffix_map[plain]
        suffix = _infer_exchange_suffix(plain)
        if suffix:
            return f"{plain}.{suffix}"
    return None


def _plain_code(code: str) -> str:
    raw = str(code).strip().upper()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    if raw.startswith(("SH", "SZ", "BJ")):
        raw = raw[2:]
    return raw


def _infer_exchange_suffix(plain_code: str) -> str | None:
    if plain_code.startswith(("60", "68", "90")):
        return "SH"
    if plain_code.startswith(("00", "30", "20")):
        return "SZ"
    if plain_code.startswith(("4", "8", "92")):
        return "BJ"
    return None


def _realtime_trade_date(row, fallback: str | None = None) -> str:
    for col in ("trade_date", "date"):
        if col not in row or pd.isna(row.get(col)):
            continue
        normalized = "".join(ch for ch in str(row.get(col)) if ch.isdigit())
        if len(normalized) >= 8:
            return normalized[:8]
    if fallback:
        normalized = "".join(ch for ch in str(fallback) if ch.isdigit())
        if len(normalized) >= 8:
            return normalized[:8]
    return datetime.now().strftime("%Y%m%d")


def _realtime_timestamp(row, trade_date: str) -> datetime:
    time_text = ""
    if "time" in row and not pd.isna(row.get("time")):
        time_text = str(row.get("time")).strip()
    compact_time = "".join(ch for ch in time_text if ch.isdigit())
    if len(compact_time) >= 6:
        try:
            return datetime.strptime(f"{trade_date}{compact_time[:6]}", "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return datetime.now()
