"""Tests for local market snapshot adapter."""

import pandas as pd
import pytest

from src.live.signal_engine import build_live_decisions
from src.live.snapshot import (
    snapshots_from_daily_df,
    snapshots_from_file,
    snapshots_from_realtime_df,
)
from src.schemas.live import LiveAccountStateV1, TargetHoldingV1


def _daily_df() -> pd.DataFrame:
    return pd.DataFrame({
        "ts_code": ["300001.SZ", "300002.SZ", "300001.SZ", "300003.SZ"],
        "trade_date": ["20260526", "20260526", "20260527", "20260527"],
        "open": [10.0, 20.0, 12.0, 5.0],
        "high": [10.5, 20.5, 12.2, 5.1],
        "low": [9.8, 19.8, 11.8, 4.9],
        "close": [10.2, 20.2, 12.0, None],
        "pre_close": [10.0, 20.0, 10.0, 5.0],
        "vol": [1000.0, 2000.0, 3000.0, 4000.0],
    })


def test_snapshots_from_daily_df_uses_latest_trade_date_by_default():
    snapshots = snapshots_from_daily_df(_daily_df())

    assert [s.ts_code for s in snapshots] == ["300001.SZ"]
    assert snapshots[0].trade_date == "20260527"
    assert snapshots[0].last_price == 12.0
    assert snapshots[0].open == 12.0
    assert snapshots[0].volume == 3000.0
    assert snapshots[0].source == "daily_cache"


def test_snapshots_from_daily_df_can_select_explicit_trade_date():
    snapshots = snapshots_from_daily_df(_daily_df(), trade_date="20260526", source="fixture")

    assert [s.ts_code for s in snapshots] == ["300001.SZ", "300002.SZ"]
    assert all(s.trade_date == "20260526" for s in snapshots)
    assert all(s.source == "fixture" for s in snapshots)


def test_snapshots_from_daily_df_marks_limit_flags():
    snapshots = snapshots_from_daily_df(pd.DataFrame({
        "ts_code": ["300001.SZ", "300002.SZ"],
        "trade_date": ["20260527", "20260527"],
        "close": [12.0, 8.0],
        "pre_close": [10.0, 10.0],
    }))

    by_code = {s.ts_code: s for s in snapshots}
    assert by_code["300001.SZ"].limit_up is True
    assert by_code["300002.SZ"].limit_down is True


def test_snapshots_from_daily_df_missing_required_columns_fails_fast():
    with pytest.raises(ValueError):
        snapshots_from_daily_df(pd.DataFrame({"ts_code": ["300001.SZ"]}))


def test_missing_price_row_becomes_blocked_decision_downstream():
    snapshots = snapshots_from_daily_df(_daily_df(), trade_date="20260527")
    account = LiveAccountStateV1(cash=100_000.0, total_value=100_000.0)
    targets = [
        TargetHoldingV1(ts_code="300003.SZ", target_weight=0.1, target_shares=100)
    ]

    decisions = build_live_decisions(
        account=account,
        targets=targets,
        snapshots=snapshots,
        strategy_name="snapshot_test",
    )

    assert decisions[0].intent.action == "blocked"
    assert decisions[0].intent.risk_flags == ["missing_snapshot"]


def test_snapshots_from_file_reads_csv(tmp_path):
    path = tmp_path / "daily.csv"
    _daily_df().to_csv(path, index=False)

    snapshots = snapshots_from_file(path, trade_date="20260526", source="csv_fixture")

    assert len(snapshots) == 2
    assert snapshots[0].source == "csv_fixture"


def test_snapshots_from_realtime_df_normalizes_tushare_quotes():
    df = pd.DataFrame([{
        "code": "000001",
        "date": "2026-06-04",
        "time": "10:15:30",
        "price": "11.20",
        "open": "11.00",
        "high": "11.30",
        "low": "10.90",
        "pre_close": "10.00",
        "volume": "12345",
    }])

    snapshots = snapshots_from_realtime_df(
        df,
        ts_codes=["000001.SZ"],
        source="tushare_realtime",
    )

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.ts_code == "000001.SZ"
    assert snapshot.trade_date == "20260604"
    assert snapshot.timestamp.isoformat() == "2026-06-04T10:15:30"
    assert snapshot.last_price == 11.2
    assert snapshot.pre_close == 10.0
    assert snapshot.volume == 12345.0
    assert snapshot.source == "tushare_realtime"


def test_snapshots_from_realtime_df_skips_zero_price_rows():
    df = pd.DataFrame([{
        "code": "000001",
        "date": "2026-06-04",
        "price": "0",
        "pre_close": "10.00",
    }])

    assert snapshots_from_realtime_df(df, ts_codes=["000001.SZ"]) == []
