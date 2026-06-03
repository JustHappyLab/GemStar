"""Tests for generated trade status reports."""

from datetime import datetime
import json

from src.live.status_report import build_trade_status_payload, write_trade_status
from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    LivePositionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
    TradingIntentV1,
)


def test_write_trade_status_json_and_markdown(tmp_path):
    account = LiveAccountStateV1(
        cash=50_000,
        total_value=70_000,
        positions=[
            LivePositionV1(
                ts_code="300750.SZ",
                shares=200,
                avg_cost=100.0,
                last_price=105.0,
                market_value=21_000,
            )
        ],
    )
    snapshots = [
        MarketSnapshotV1(
            ts_code="300750.SZ",
            trade_date="20260527",
            timestamp=datetime(2026, 5, 27, 10, 0, 0),
            last_price=110.0,
        )
    ]
    targets = [
        TargetHoldingV1(
            ts_code="300750.SZ",
            target_weight=0.5,
            target_shares=300,
            reason="top from strategy",
        )
    ]
    decisions = [
        LiveDecisionV1(
            decision_id="d1",
            strategy_name="s1",
            ts_code="300750.SZ",
            intent=TradingIntentV1(
                action="add",
                shares=100,
                reference_price=110.0,
                reason="target shares exceed current shares",
            ),
        )
    ]

    payload = build_trade_status_payload(
        ref_date="20260527",
        run_id="run-1",
        account=account,
        targets=targets,
        snapshots=snapshots,
        decisions=decisions,
        strategies=["s1"],
        symbol_names={"300750.SZ": "宁德时代"},
    )
    json_path, md_path = write_trade_status(tmp_path, payload)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["rows"][0]["label"] == "300750.SZ 宁德时代"
    assert data["rows"][0]["diff_shares"] == 100
    md = md_path.read_text(encoding="utf-8")
    assert "# GemStar Trade Status" in md
    assert "300750.SZ 宁德时代" in md
    assert "| 标的 | 当前股数 |" in md
