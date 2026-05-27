"""A-share market clock helpers for the live radar loop.

CALLING SPEC:
    session = session_for_time(now=datetime) -> TradingSession
    active = is_trading_time(now=datetime, is_trading_day=bool) -> bool
    seconds = next_poll_seconds(
        now=datetime,
        active_interval=int,
        idle_interval=int,
        is_trading_day=bool,
    ) -> int

SIDE EFFECTS:
    None. Trading-day knowledge is injected by the caller.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal


TradingSession = Literal[
    "pre_open",
    "morning",
    "lunch",
    "afternoon",
    "after_close",
]

_MORNING_START = time(9, 30)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 0)
_AFTERNOON_END = time(15, 0)


def session_for_time(now: datetime) -> TradingSession:
    """Return the A-share session bucket for *now*."""
    current = now.time()
    if current < _MORNING_START:
        return "pre_open"
    if _MORNING_START <= current < _MORNING_END:
        return "morning"
    if _MORNING_END <= current < _AFTERNOON_START:
        return "lunch"
    if _AFTERNOON_START <= current < _AFTERNOON_END:
        return "afternoon"
    return "after_close"


def is_trading_time(now: datetime, is_trading_day: bool = True) -> bool:
    """Return True only during continuous A-share trading sessions."""
    if not is_trading_day:
        return False
    return session_for_time(now) in {"morning", "afternoon"}


def next_poll_seconds(
    now: datetime,
    active_interval: int = 30,
    idle_interval: int = 300,
    is_trading_day: bool = True,
) -> int:
    """Choose the live loop polling cadence for the current market state."""
    if active_interval <= 0:
        raise ValueError("active_interval must be positive")
    if idle_interval <= 0:
        raise ValueError("idle_interval must be positive")
    if is_trading_time(now, is_trading_day=is_trading_day):
        return active_interval
    return idle_interval
