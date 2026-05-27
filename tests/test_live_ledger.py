"""Tests for append-only paper trading ledger."""

from datetime import datetime

import pytest

from src.live.ledger import (
    append_paper_trade,
    build_paper_trade_record,
    read_paper_trades,
)
from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    LivePositionV1,
    TradingIntentV1,
)


NOW = datetime(2026, 5, 27, 10, 0, 0)


def _decision(action: str, shares: int) -> LiveDecisionV1:
    return LiveDecisionV1(
        decision_id=f"20260527-300750.SZ-{action}-100",
        created_at=NOW,
        strategy_name="chinext_lstm_mf8",
        ts_code="300750.SZ",
        intent=TradingIntentV1(
            action=action,
            shares=shares,
            reference_price=100.5,
            reason="test decision",
        ),
    )


def _account(shares: int = 0, bought_today: bool = False) -> LiveAccountStateV1:
    positions = []
    if shares:
        positions.append(
            LivePositionV1(
                ts_code="300750.SZ",
                shares=shares,
                avg_cost=100.0,
                bought_today=bought_today,
            )
        )
    return LiveAccountStateV1(
        as_of=NOW,
        cash=100_000.0,
        total_value=100_000.0,
        positions=positions,
    )


def test_build_paper_trade_record_requires_confirmation():
    with pytest.raises(ValueError):
        build_paper_trade_record(
            account=_account(),
            decision=_decision("buy", 100),
            execution_id="exec-1",
            trade_date="20260527",
            fill_price=100.5,
            confirmed=False,
        )


def test_build_paper_trade_record_updates_buy_position():
    record = build_paper_trade_record(
        account=_account(),
        decision=_decision("buy", 200),
        execution_id="exec-1",
        trade_date="20260527",
        fill_price=100.5,
        confirmed=True,
    )

    assert record.action == "buy"
    assert record.executed is True
    assert record.confirmed is True
    assert record.position_after_shares == 200


def test_build_paper_trade_record_rejects_non_executable_action():
    with pytest.raises(ValueError):
        build_paper_trade_record(
            account=_account(),
            decision=_decision("hold", 0),
            execution_id="exec-1",
            trade_date="20260527",
            fill_price=100.5,
            confirmed=True,
        )


def test_build_paper_trade_record_enforces_t_plus_1_sell_rule():
    with pytest.raises(ValueError):
        build_paper_trade_record(
            account=_account(shares=200, bought_today=True),
            decision=_decision("sell", 100),
            execution_id="exec-1",
            trade_date="20260527",
            fill_price=100.5,
            confirmed=True,
        )


def test_build_paper_trade_record_rejects_oversell():
    with pytest.raises(ValueError):
        build_paper_trade_record(
            account=_account(shares=100),
            decision=_decision("sell", 200),
            execution_id="exec-1",
            trade_date="20260527",
            fill_price=100.5,
            confirmed=True,
        )


def test_append_and_read_paper_trades_reject_duplicate_execution_id(tmp_path):
    path = tmp_path / "paper" / "ledger.jsonl"
    record = build_paper_trade_record(
        account=_account(),
        decision=_decision("buy", 200),
        execution_id="exec-1",
        trade_date="20260527",
        fill_price=100.5,
        confirmed=True,
    )

    append_paper_trade(path, record)
    records = read_paper_trades(path)

    assert len(records) == 1
    assert records[0].execution_id == "exec-1"
    with pytest.raises(ValueError):
        append_paper_trade(path, record)
