"""Tests for long-running live radar loop with injected clock/sleep."""

from datetime import datetime, timedelta
import threading

from src.live.loop import run_live_loop
from src.live.decision_messages import notification_from_decision
from src.notify.message import NotificationMessageV1
from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
    TradingIntentV1,
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
    assert "结论：建议买入 200 股（可执行）" in messages[0].body
    assert "估算金额：20,100.00" in messages[0].body
    assert "置信度" not in messages[0].body
    assert "风险/限制：无" in messages[0].body
    assert "理由：目标股数高于当前持仓；策略原因：入选策略排名靠前" in messages[0].body


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


def test_run_live_loop_suppresses_notifications_for_stale_required_date():
    messages = []

    result = run_live_loop(
        account_loader=_account,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=messages.append,
        strategy_name="chinext_lstm_mf8",
        required_trade_date="20260528",
        max_cycles=1,
    )

    assert messages == []
    assert result.notifications == 0
    assert result.decisions == 1


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


def test_notification_message_explains_blocked_limit_up() -> None:
    decision = LiveDecisionV1(
        decision_id="20260527-300750.SZ-blocked-200",
        created_at=datetime(2026, 5, 27, 10, 0, 0),
        strategy_name="chinext_lstm_mf8",
        ts_code="300750.SZ",
        severity="critical",
        intent=TradingIntentV1(
            action="blocked",
            shares=0,
            reference_price=120.0,
            reason="buy blocked because the stock is limit-up",
            risk_flags=["limit_up"],
        ),
    )

    message = notification_from_decision(decision, symbol_names={"300750.SZ": "宁德时代"})

    assert message.title == "[受限] 300750.SZ 宁德时代"
    assert "结论：暂不执行（受限，不能下单）" in message.body
    assert "理由：买入受限：标的涨停" in message.body
    assert "风险/限制：涨停，无法追买" in message.body


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


def test_run_live_loop_dedupes_extra_alert_messages():
    messages = []

    def account_with_target_position() -> LiveAccountStateV1:
        return LiveAccountStateV1(
            cash=80_000.0,
            total_value=100_000.0,
            positions=[{
                "ts_code": "300750.SZ",
                "shares": 200,
                "avg_cost": 100.0,
                "last_price": 100.5,
                "market_value": 20_100.0,
            }],
        )

    def alert_fn(_account, _targets, _snapshots, now):
        return [
            NotificationMessageV1(
                message_id="price-20260527-300750.SZ-up-300",
                created_at=now,
                severity="warning",
                title="[涨跌提醒] 300750.SZ +3.00%",
                body="price alert",
                action="price_alert",
                symbols=["300750.SZ"],
            )
        ]

    result = run_live_loop(
        account_loader=account_with_target_position,
        targets_loader=_targets,
        snapshots_loader=_snapshots,
        notify=messages.append,
        strategy_name="chinext_lstm_mf8",
        sleep_fn=lambda seconds: None,
        max_cycles=2,
        alert_fn=alert_fn,
    )

    assert len(messages) == 1
    assert messages[0].action == "price_alert"
    assert result.notifications == 1
    assert result.deduped == 1
