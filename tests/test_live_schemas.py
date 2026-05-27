"""Tests for live trading radar schemas."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    LivePositionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
    TradingIntentV1,
)


def test_live_position_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        LivePositionV1(
            ts_code="300750.SZ",
            shares=100,
            avg_cost=100.0,
            invented_field=True,
        )


def test_live_position_rejects_negative_price_and_odd_lot():
    with pytest.raises(ValidationError):
        LivePositionV1(ts_code="300750.SZ", shares=99, avg_cost=100.0)

    with pytest.raises(ValidationError):
        LivePositionV1(ts_code="300750.SZ", shares=100, avg_cost=-1.0)


def test_market_snapshot_rejects_bad_trade_date_and_price():
    with pytest.raises(ValidationError):
        MarketSnapshotV1(
            ts_code="300750.SZ",
            trade_date="2026-05-27",
            last_price=100.0,
        )

    with pytest.raises(ValidationError):
        MarketSnapshotV1(
            ts_code="300750.SZ",
            trade_date="20260527",
            last_price=0.0,
        )


def test_target_holding_bounds():
    with pytest.raises(ValidationError):
        TargetHoldingV1(
            ts_code="300750.SZ",
            target_weight=1.2,
            target_shares=100,
        )

    with pytest.raises(ValidationError):
        TargetHoldingV1(
            ts_code="300750.SZ",
            target_weight=0.2,
            target_shares=-100,
        )


def test_trading_intent_action_is_restricted():
    with pytest.raises(ValidationError):
        TradingIntentV1(
            action="panic",
            shares=100,
            reference_price=100.0,
            reason="unsupported action",
        )


def test_minimal_live_decision_serializes_stably():
    created_at = datetime(2026, 5, 27, 10, 0, 0)
    decision = LiveDecisionV1(
        decision_id="20260527-300750.SZ-buy-100",
        created_at=created_at,
        strategy_name="chinext_lstm_mf8",
        ts_code="300750.SZ",
        intent=TradingIntentV1(
            action="buy",
            shares=100,
            reference_price=100.5,
            confidence=0.8,
            reason="target shares exceed current shares",
        ),
    )

    assert decision.model_dump(mode="json") == {
        "version": "LiveDecisionV1",
        "decision_id": "20260527-300750.SZ-buy-100",
        "created_at": "2026-05-27T10:00:00",
        "strategy_name": "chinext_lstm_mf8",
        "ts_code": "300750.SZ",
        "severity": "info",
        "intent": {
            "version": "TradingIntentV1",
            "action": "buy",
            "shares": 100,
            "reference_price": 100.5,
            "confidence": 0.8,
            "reason": "target shares exceed current shares",
            "risk_flags": [],
        },
        "notify": True,
    }


def test_account_state_roundtrip():
    account = LiveAccountStateV1(
        as_of=datetime(2026, 5, 27, 10, 0, 0),
        cash=50_000.0,
        total_value=100_000.0,
        positions=[
            LivePositionV1(
                ts_code="300750.SZ",
                shares=500,
                avg_cost=100.0,
                last_price=101.0,
                market_value=50_500.0,
            )
        ],
    )

    parsed = LiveAccountStateV1.model_validate_json(account.model_dump_json())
    assert parsed.model_dump() == account.model_dump()
