"""Tests for src.reviewer.analysis — mocked Anthropic API, no live requests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.llm.client import LLMClient
from src.reviewer.analysis import review_verdict
from src.schemas.factor import FactorHealthEntry, FactorHealthReportV1
from src.schemas.metrics import BacktestResultV1, MetricsV1, SegmentMetricV1
from src.schemas.review import ReviewNotesV1
from src.schemas.verdict import HardGateResultV1, VerdictV1


# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

def _make_result() -> BacktestResultV1:
    return BacktestResultV1(
        strategy_name="test_strat",
        backtest_period="20220101~20220301",
        capital=100000.0,
        metrics=MetricsV1(
            cagr=0.15,
            sharpe=1.35,
            max_drawdown=-0.22,
            calmar=1.10,
            win_rate=0.55,
            profit_factor=1.8,
            completed_trades=150,
            annual_turnover_ratio=12.0,
            alpha=0.08,
            longest_drawdown_days=30,
        ),
        segments=[
            SegmentMetricV1(
                segment="2022",
                days=60,
                cagr=0.15,
                sharpe=1.3,
                max_drawdown=-0.20,
                alpha=0.07,
            ),
            SegmentMetricV1(
                segment="2023",
                days=60,
                cagr=0.12,
                sharpe=1.1,
                max_drawdown=-0.25,
                alpha=0.05,
            ),
        ],
    )


def _make_verdict() -> VerdictV1:
    return VerdictV1(
        strategy_id="test_strat",
        run_id="run_001",
        recommended_state="candidate",
        hard_gates=[
            HardGateResultV1(name="sharpe", passed=True, value=1.35, threshold=1.0),
            HardGateResultV1(name="calmar", passed=True, value=1.10, threshold=0.8),
            HardGateResultV1(name="max_drawdown", passed=True, value=-0.22, threshold=-0.30),
            HardGateResultV1(name="completed_trades", passed=True, value=150.0, threshold=100.0),
            HardGateResultV1(name="segment_sharpe_ir_std", passed=True, value=0.14, threshold=0.5),
        ],
    )


def _make_factor_health() -> FactorHealthReportV1:
    from datetime import date

    return FactorHealthReportV1(
        run_id="run_001",
        as_of_date=date(2026, 5, 3),
        entries=[
            FactorHealthEntry(
                factor_name="momentum_20d",
                ic_ir=0.45,
                status="healthy",
            ),
        ],
    )


def _make_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _valid_review_json() -> str:
    return json.dumps({
        "version": "ReviewNotesV1",
        "strategy_id": "test_strat",
        "run_id": "run_001",
        "verdict_summary": "candidate — 全部硬门通过",
        "explanation": "该策略在所有硬门指标上均达标，Sharpe 1.35 超过阈值 1.0，Calmar 1.10 超过阈值 0.8，最大回撤 -22% 在 -30% 以内。",
        "risk_highlights": [
            "max_drawdown -22% 接近 -30% 阈值",
            "分段Sharpe标准差0.14偏低，表现稳定",
        ],
        "confidence": 0.85,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReviewVerdict:

    def test_valid_response_returns_review_notes(self) -> None:
        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(
                _valid_review_json()
            )

            llm = LLMClient(api_key="test-key")
            result = review_verdict(
                _make_result(), _make_verdict(), _make_factor_health(), llm,
            )

        assert isinstance(result, ReviewNotesV1)
        assert result.strategy_id == "test_strat"
        assert result.run_id == "run_001"
        assert result.version == "ReviewNotesV1"
        assert result.confidence == pytest.approx(0.85)

    def test_verdict_summary_present(self) -> None:
        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(
                _valid_review_json()
            )

            llm = LLMClient(api_key="test-key")
            result = review_verdict(
                _make_result(), _make_verdict(), _make_factor_health(), llm,
            )

        assert result.verdict_summary != ""
        assert "candidate" in result.verdict_summary

    def test_no_factor_health_still_works(self) -> None:
        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(
                _valid_review_json()
            )

            llm = LLMClient(api_key="test-key")
            result = review_verdict(
                _make_result(), _make_verdict(), None, llm,
            )

        assert isinstance(result, ReviewNotesV1)
        assert result.strategy_id == "test_strat"

    def test_malformed_json_retries_then_raises(self) -> None:
        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(
                "not valid json"
            )

            llm = LLMClient(api_key="test-key")
            with pytest.raises(ValueError):
                review_verdict(
                    _make_result(), _make_verdict(), None, llm,
                )
