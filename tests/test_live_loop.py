"""Tests for long-running live radar loop with injected clock/sleep."""

from datetime import datetime, timedelta
import threading

from src.live.loop import run_live_loop
from src.schemas.live import (
    LiveAccountStateV1,
    MarketSnapshotV1,
    TargetHoldingV1,
)


def _account() -> LiveAccountStateV1:
    return LiveAccountStateV1(
        as_of=datetime(2026, 5, 27, 10, 0, 0),
        cash=100_000.0,
        total_value=100_000.0,
        positions=[],
    )


def _targets() -> list[TargetHoldingV1]:
    return [
        TargetHoldingV1(
            ts_code="300750.SZ",
            target_weight=0.2,
            target_shares=200,
            reason="top ranked",
        )
    ]


def _snapshots() -> list[MarketSnapshotV1]:
    return [
        MarketSnapshotV1(
            ts_code="300750.SZ",
            trade_date="20260527",
            timestamp=datetime(2026, 5, 27, 10, 0, 0),
            last_price=100.5,
            source="test",
        )
    ]


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def test_run_live_loop_uses_active_interval_during_trading_time():
    clock = FakeClock(datetime(2026, 5, 27, 10, 0, 0))
    sleeps: list[int] = []
    messages = []

    def sleep(seconds: int) -> None:
        sleeps.append(seconds)
        clock.sleep(seconds)

    result = run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=messages.append,
        strategy_name="chinext_lstm_mf8",
        now_fn=clock,
        sleep_fn=sleep,
        active_interval=15,
        idle_interval=600,
        max_cycles=2,
    )

    assert sleeps == [15]
    assert result.cycles == 2
    assert result.notifications == 1
    assert result.deduped == 1
    assert messages[0].title == "[买入] 300750.SZ"
    assert "状态：可执行" in messages[0].body
    assert "置信度" not in messages[0].body
    assert "风险：无" in messages[0].body


def test_run_live_loop_uses_idle_interval_outside_trading_time():
    clock = FakeClock(datetime(2026, 5, 27, 8, 0, 0))
    sleeps: list[int] = []

    result = run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=lambda message: None,
        strategy_name="chinext_lstm_mf8",
        now_fn=clock,
        sleep_fn=lambda seconds: sleeps.append(seconds),
        active_interval=15,
        idle_interval=600,
        max_cycles=2,
    )

    assert sleeps == [600]
    assert result.cycles == 2


def test_run_live_loop_formats_symbol_names_when_available():
    messages = []

    run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=messages.append,
        strategy_name="chinext_lstm_mf8",
        symbol_names={"300750.SZ": "宁德时代"},
        max_cycles=1,
    )

    assert messages[0].title == "[买入] 300750.SZ 宁德时代"
    assert "标的：300750.SZ 宁德时代" in messages[0].body
    assert messages[0].symbol_names == {"300750.SZ": "宁德时代"}


def test_run_live_loop_respects_non_trading_day_flag():
    clock = FakeClock(datetime(2026, 5, 27, 10, 0, 0))
    sleeps: list[int] = []

    run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=lambda message: None,
        strategy_name="chinext_lstm_mf8",
        now_fn=clock,
        sleep_fn=lambda seconds: sleeps.append(seconds),
        is_trading_day_fn=lambda now: False,
        active_interval=15,
        idle_interval=600,
        max_cycles=2,
    )

    assert sleeps == [600]


def test_run_live_loop_stops_cleanly_after_sleep_sets_event():
    stop_event = threading.Event()
    sleeps: list[int] = []

    def sleep(seconds: int) -> None:
        sleeps.append(seconds)
        stop_event.set()

    result = run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=lambda message: None,
        strategy_name="chinext_lstm_mf8",
        stop_event=stop_event,
        now_fn=lambda: datetime(2026, 5, 27, 10, 0, 0),
        sleep_fn=sleep,
        active_interval=15,
        idle_interval=600,
    )

    assert sleeps == [15]
    assert result.cycles == 1


def test_run_live_loop_emits_heartbeat_events():
    heartbeats = []

    run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=lambda message: None,
        strategy_name="chinext_lstm_mf8",
        now_fn=lambda: datetime(2026, 5, 27, 10, 0, 0),
        sleep_fn=lambda seconds: None,
        active_interval=15,
        idle_interval=600,
        max_cycles=1,
        heartbeat_fn=heartbeats.append,
    )

    assert heartbeats == [{
        "now": "2026-05-27T10:00:00",
        "cycle": 1,
        "decisions": 1,
        "notifications": 1,
        "deduped": 0,
        "sleep_seconds": 15,
        "is_trading_day": True,
    }]
