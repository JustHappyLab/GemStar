"""Scheduler utilities — preset parsing, trading-day checks, time waiting.

CALLING SPEC:
    parse_schedule(value) -> ScheduleConfig | None
    is_trading_day(date_str, trade_cal_df) -> bool
    next_trading_day(from_date, trade_cal_df) -> date
    wait_until(target_time, stop_event=None) -> bool
    last_run_status(db_path, date_prefix) -> str | None

SIDE EFFECTS:
    wait_until blocks the calling thread.
    last_run_status reads from state.db.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta

import pandas as pd

from src.cli.config import ScheduleConfig, parse_schedule  # noqa: F401


def is_trading_day(date_str: str, trade_cal_df: pd.DataFrame) -> bool:
    """Check if *date_str* (YYYYMMDD) is a trading day."""
    if "is_open" in trade_cal_df.columns:
        open_days = trade_cal_df[trade_cal_df["is_open"] == 1]["cal_date"].astype(str)
    else:
        open_days = trade_cal_df["cal_date"].astype(str)
    return date_str in open_days.values


def next_trading_day(from_date: date, trade_cal_df: pd.DataFrame) -> date:
    """Return the next trading day on or after *from_date*."""
    if "is_open" in trade_cal_df.columns:
        open_days = (
            trade_cal_df[trade_cal_df["is_open"] == 1]["cal_date"]
            .astype(str)
            .sort_values()
            .tolist()
        )
    else:
        open_days = trade_cal_df["cal_date"].astype(str).sort_values().tolist()
    from_str = from_date.strftime("%Y%m%d")
    for d in open_days:
        if d >= from_str:
            return datetime.strptime(d, "%Y%m%d").date()
    return from_date + timedelta(days=1)


def wait_until(target_time: str, stop_event=None, check_interval: int = 30) -> bool:
    """Block until *target_time* (HH:MM). Returns True on timeout, False if stopped.

    If the target time has already passed today, returns immediately.
    *stop_event*: optional threading.Event; if set, returns False early.
    """
    if stop_event is not None and stop_event.is_set():
        return False

    h, m = map(int, target_time.split(":"))
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= target:
        return True

    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return True
        if stop_event is not None and stop_event.is_set():
            return False
        time.sleep(min(check_interval, remaining))


def last_run_status(db_path: str, date_prefix: str) -> str | None:
    """Query the most recent run status matching *date_prefix* (e.g. '20260503').

    Returns the status string or None if no matching run exists.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM runs WHERE run_id LIKE ? ORDER BY started_at DESC LIMIT 1",
            (f"{date_prefix}%",),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()
