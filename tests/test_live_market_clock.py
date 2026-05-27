"""Tests for A-share live market clock helpers."""

from datetime import datetime

import pytest

from src.live.market_clock import is_trading_time, next_poll_seconds, session_for_time


def _dt(hh: int, mm: int) -> datetime:
    return datetime(2026, 5, 27, hh, mm, 0)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_dt(9, 29), "pre_open"),
        (_dt(9, 30), "morning"),
        (_dt(11, 29), "morning"),
        (_dt(11, 30), "lunch"),
        (_dt(12, 59), "lunch"),
        (_dt(13, 0), "afternoon"),
        (_dt(14, 59), "afternoon"),
        (_dt(15, 0), "after_close"),
    ],
)
def test_session_for_time_boundaries(now, expected):
    assert session_for_time(now) == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_dt(9, 29), False),
        (_dt(9, 30), True),
        (_dt(11, 30), False),
        (_dt(13, 0), True),
        (_dt(15, 0), False),
    ],
)
def test_is_trading_time(now, expected):
    assert is_trading_time(now) is expected


def test_is_trading_time_respects_trading_day_flag():
    assert is_trading_time(_dt(10, 0), is_trading_day=False) is False


def test_next_poll_seconds_uses_active_interval_during_session():
    assert next_poll_seconds(_dt(10, 0), active_interval=15, idle_interval=600) == 15
    assert next_poll_seconds(_dt(13, 30), active_interval=15, idle_interval=600) == 15


def test_next_poll_seconds_uses_idle_interval_outside_session():
    assert next_poll_seconds(_dt(8, 0), active_interval=15, idle_interval=600) == 600
    assert next_poll_seconds(_dt(12, 0), active_interval=15, idle_interval=600) == 600
    assert next_poll_seconds(_dt(16, 0), active_interval=15, idle_interval=600) == 600


def test_next_poll_seconds_rejects_non_positive_intervals():
    with pytest.raises(ValueError):
        next_poll_seconds(_dt(10, 0), active_interval=0)

    with pytest.raises(ValueError):
        next_poll_seconds(_dt(10, 0), idle_interval=0)
