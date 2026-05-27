"""Tests for deterministic live signal engine decisions."""

from datetime import datetime

from src.live.signal_engine import build_live_decisions
from src.schemas.live import (
    LiveAccountStateV1,
    LivePositionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
)


NOW = datetime(2026, 5, 27, 10, 0, 0)


def _account(shares: int = 0) -> LiveAccountStateV1:
    positions = []
    if shares:
        positions.append(
            LivePositionV1(ts_code="300750.SZ", shares=shares, avg_cost=100.0)
        )
    return LiveAccountStateV1(
        as_of=NOW,
        cash=100_000.0,
        total_value=100_000.0,
        positions=positions,
    )


def _target(shares: int) -> TargetHoldingV1:
    return TargetHoldingV1(
        ts_code="300750.SZ",
        target_weight=0.5,
        target_shares=shares,
        reason="top ranked by live strategy",
    )


def _snapshot(limit_up: bool = False, limit_down: bool = False) -> MarketSnapshotV1:
    return MarketSnapshotV1(
        ts_code="300750.SZ",
        trade_date="20260527",
        timestamp=NOW,
        last_price=100.5,
        limit_up=limit_up,
        limit_down=limit_down,
        source="test",
    )


def _only_decision(account, targets, snapshots):
    decisions = build_live_decisions(
        account=account,
        targets=targets,
        snapshots=snapshots,
        strategy_name="chinext_lstm_mf8",
        created_at=NOW,
    )
    assert len(decisions) == 1
    return decisions[0]


def test_build_live_decisions_emits_buy_for_new_target():
    decision = _only_decision(_account(0), [_target(200)], [_snapshot()])

    assert decision.decision_id == "20260527-300750.SZ-buy-200"
    assert decision.intent.action == "buy"
    assert decision.intent.shares == 200
    assert decision.intent.reference_price == 100.5
    assert decision.intent.confidence == 0.8
    assert "target shares exceed current shares" in decision.intent.reason
    assert decision.notify is True


def test_build_live_decisions_emits_sell_when_target_removed():
    decision = _only_decision(_account(300), [], [_snapshot()])

    assert decision.decision_id == "20260527-300750.SZ-sell-0"
    assert decision.intent.action == "sell"
    assert decision.intent.shares == 300
    assert decision.severity == "warning"


def test_build_live_decisions_emits_hold_inside_one_lot_threshold():
    decision = _only_decision(_account(200), [_target(200)], [_snapshot()])

    assert decision.intent.action == "hold"
    assert decision.intent.shares == 0
    assert decision.notify is False


def test_build_live_decisions_blocks_buy_on_limit_up():
    decision = _only_decision(_account(0), [_target(200)], [_snapshot(limit_up=True)])

    assert decision.intent.action == "blocked"
    assert decision.intent.shares == 0
    assert decision.intent.risk_flags == ["limit_up"]
    assert decision.severity == "critical"


def test_build_live_decisions_blocks_sell_on_limit_down():
    decision = _only_decision(_account(300), [], [_snapshot(limit_down=True)])

    assert decision.intent.action == "blocked"
    assert decision.intent.shares == 0
    assert decision.intent.risk_flags == ["limit_down"]


def test_build_live_decisions_blocks_missing_snapshot():
    decision = _only_decision(_account(0), [_target(200)], [])

    assert decision.decision_id == "20260527-300750.SZ-blocked-200"
    assert decision.intent.action == "blocked"
    assert decision.intent.reference_price is None
    assert decision.intent.risk_flags == ["missing_snapshot"]
