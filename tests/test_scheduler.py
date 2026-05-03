"""Tests for orchestrator/scheduler.py — preset parsing, trading day, wait_until."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from src.cli.config import ScheduleConfig, parse_schedule
from src.orchestrator.scheduler import is_trading_day, last_run_status, next_trading_day, wait_until


# ---------------------------------------------------------------------------
# parse_schedule
# ---------------------------------------------------------------------------

def test_parse_preset():
    s = parse_schedule("收盘后")
    assert s == ScheduleConfig(fetch="15:30", run="16:00")

def test_parse_preset_morning():
    s = parse_schedule("盘前")
    assert s == ScheduleConfig(fetch="06:00", run="07:00")

def test_parse_preset_night():
    s = parse_schedule("深夜")
    assert s == ScheduleConfig(fetch="15:30", run="02:00")

def test_parse_simple_time():
    s = parse_schedule("16:00")
    assert s == ScheduleConfig(fetch="16:00", run="16:00")

def test_parse_dict():
    s = parse_schedule({"fetch": "15:00", "run": "18:00"})
    assert s == ScheduleConfig(fetch="15:00", run="18:00")

def test_parse_none():
    assert parse_schedule(None) is None

def test_parse_invalid_preset():
    with pytest.raises(ValueError, match="Invalid schedule"):
        parse_schedule("不存在的预设")


# ---------------------------------------------------------------------------
# is_trading_day
# ---------------------------------------------------------------------------

def _make_cal(dates: list[str], opens: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"cal_date": dates, "is_open": opens})


def test_is_trading_day_true():
    cal = _make_cal(["20260504", "20260505", "20260506"], [0, 1, 1])
    assert is_trading_day("20260505", cal) is True

def test_is_trading_day_false():
    cal = _make_cal(["20260504", "20260505", "20260506"], [0, 1, 1])
    assert is_trading_day("20260504", cal) is False

def test_is_trading_day_missing():
    cal = _make_cal(["20260504"], [1])
    assert is_trading_day("20260510", cal) is False


# ---------------------------------------------------------------------------
# next_trading_day
# ---------------------------------------------------------------------------

def test_next_trading_day_same_day():
    cal = _make_cal(["20260504", "20260505"], [1, 1])
    result = next_trading_day(date(2026, 5, 5), cal)
    assert result == date(2026, 5, 5)

def test_next_trading_day_skips_weekend():
    cal = _make_cal(["20260508", "20260509", "20260512"], [1, 0, 1])
    result = next_trading_day(date(2026, 5, 9), cal)
    assert result == date(2026, 5, 12)


# ---------------------------------------------------------------------------
# wait_until
# ---------------------------------------------------------------------------

def test_wait_until_past_returns_immediately():
    # A time that has certainly passed
    result = wait_until("00:00")
    assert result is True

def test_wait_until_stopped():
    import threading

    stop = threading.Event()
    stop.set()  # already stopped
    result = wait_until("23:59", stop_event=stop)
    assert result is False


# ---------------------------------------------------------------------------
# last_run_status
# ---------------------------------------------------------------------------

def test_last_run_status_found(tmp_path):
    from src.orchestrator.state_db import connect, migrate

    db_path = str(tmp_path / "test.db")
    conn = connect(db_path)
    migrate(conn)
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, ?)",
        ("20260503-abc12345", "2026-05-03T16:00:00", "completed"),
    )
    conn.commit()
    conn.close()

    assert last_run_status(db_path, "20260503") == "completed"

def test_last_run_status_not_found(tmp_path):
    from src.orchestrator.state_db import connect, migrate

    db_path = str(tmp_path / "test.db")
    conn = connect(db_path)
    migrate(conn)
    conn.close()

    assert last_run_status(db_path, "20260503") is None
