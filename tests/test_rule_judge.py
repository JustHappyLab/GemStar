"""Tests for src/judge/rules.py — pure-Python hard-gate judge.

CALLING SPEC:
    Each test constructs a ``BacktestResultV1`` with controlled metric values,
    calls ``evaluate()``, and asserts the expected VerdictV1 shape.
"""

from __future__ import annotations

from src.judge.rules import evaluate
from src.schemas.metrics import BacktestResultV1, MetricsV1, SegmentMetricV1
from src.schemas.verdict import VerdictV1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    *,
    sharpe: float = 1.5,
    calmar: float = 1.0,
    max_drawdown: float = -0.15,
    completed_trades: int = 200,
    segments: list[SegmentMetricV1] | None = None,
) -> BacktestResultV1:
    """Build a BacktestResultV1 with sensible defaults (all gates pass)."""
    return BacktestResultV1(
        strategy_name="test_strat",
        run_id="run-001",
        metrics=MetricsV1(
            sharpe=sharpe,
            calmar=calmar,
            max_drawdown=max_drawdown,
            completed_trades=completed_trades,
        ),
        segments=segments or [],
    )


# ---------------------------------------------------------------------------
# All gates pass
# ---------------------------------------------------------------------------

def test_all_gates_pass_returns_candidate():
    result = _make_result()
    verdict = evaluate(result, strategy_id="s1")

    assert isinstance(verdict, VerdictV1)
    assert verdict.recommended_state == "candidate"
    assert verdict.blocking_issues == []
    assert all(g.passed for g in verdict.hard_gates)


# ---------------------------------------------------------------------------
# Individual gate failures
# ---------------------------------------------------------------------------

def test_sharpe_too_low_rejects():
    result = _make_result(sharpe=0.5)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert any("sharpe" in issue for issue in verdict.blocking_issues)


def test_calmar_too_low_rejects():
    result = _make_result(calmar=0.3)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert any("calmar" in issue for issue in verdict.blocking_issues)


def test_max_dd_too_deep_rejects():
    result = _make_result(max_drawdown=-0.45)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert any("max_drawdown" in issue for issue in verdict.blocking_issues)


def test_zero_completed_trades_rejects():
    result = _make_result(completed_trades=0)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert any("completed_trades" in issue for issue in verdict.blocking_issues)


def test_segment_ir_std_too_high_rejects():
    """Segments with wildly different sharpes fail the consistency gate."""
    segments = [
        SegmentMetricV1(segment="2022", sharpe=3.0),
        SegmentMetricV1(segment="2023", sharpe=0.1),
        SegmentMetricV1(segment="2024", sharpe=2.5),
    ]
    result = _make_result(segments=segments)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert any("segment_sharpe_ir_std" in issue for issue in verdict.blocking_issues)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_exact_threshold_values_pass():
    """Values exactly at the threshold boundary should pass."""
    result = _make_result(
        sharpe=1.0,
        calmar=0.8,
        max_drawdown=-0.30,
        completed_trades=100,
    )
    verdict = evaluate(result)

    assert verdict.recommended_state == "candidate"


def test_no_segments_skips_ir_gate():
    """With zero or one segment, the IR std gate degenerates to 0.0 (passes)."""
    result = _make_result(segments=[])
    verdict = evaluate(result)

    assert verdict.recommended_state == "candidate"


def test_single_segment_skips_ir_gate():
    result = _make_result(segments=[SegmentMetricV1(segment="2024", sharpe=2.0)])
    verdict = evaluate(result)

    assert verdict.recommended_state == "candidate"


def test_strategy_id_propagated():
    result = _make_result()
    verdict = evaluate(result, strategy_id="my-strategy")
    assert verdict.strategy_id == "my-strategy"


def test_fallback_strategy_id_from_result():
    result = _make_result()
    verdict = evaluate(result)
    assert verdict.strategy_id == "test_strat"


def test_multiple_failures_populate_all_blocking_issues():
    result = _make_result(sharpe=0.1, calmar=0.1, completed_trades=0)
    verdict = evaluate(result)

    assert verdict.recommended_state == "rejected"
    assert len(verdict.blocking_issues) >= 3
