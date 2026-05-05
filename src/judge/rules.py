"""Pure-Python hard-gate judge — Opus plan section 12.

CALLING SPEC:
    ``evaluate(result: BacktestResultV1, strategy_id: str = "") -> VerdictV1``
    Evaluates five hard gates against backtest metrics and returns a VerdictV1
    with per-gate pass/fail and recommended_state.

HARD GATES:
    1. Sharpe >= 1.0
    2. Calmar >= 0.8
    3. max_drawdown <= 0.30  (absolute drawdown fraction, 0.30 = 30%)
    4. completed_trades >= 100
    5. Segment Sharpe IR std <= 0.5  (consistency across yearly segments)

SIDE EFFECTS:
    None — pure function.
"""

from __future__ import annotations

import statistics

from src.schemas.metrics import BacktestResultV1, SegmentMetricV1
from src.schemas.verdict import HardGateResultV1, VerdictV1


# ---------------------------------------------------------------------------
# Thresholds (from Opus plan §12)
# ---------------------------------------------------------------------------
_SHARPE_MIN = 1.0
_CALMAR_MIN = 0.8
_MAX_DD_MAX = 0.30
_COMPLETED_TRADES_MIN = 100
_SEGMENT_IR_STD_MAX = 0.5


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate(result: BacktestResultV1, *, strategy_id: str = "") -> VerdictV1:
    """Run all hard gates on *result* and return a VerdictV1.

    Parameters
    ----------
    result:
        A completed backtest result containing metrics and optional segments.
    strategy_id:
        Free-form identifier stamped onto the verdict for traceability.

    Returns
    -------
    VerdictV1
        recommended_state is ``"candidate"`` only when **every** gate passes.
    """
    metrics = result.metrics
    gates: list[HardGateResultV1] = []

    # Gate 1 — Sharpe
    gates.append(_check("sharpe", metrics.sharpe, _SHARPE_MIN, ge=True))

    # Gate 2 — Calmar
    gates.append(_check("calmar", metrics.calmar, _CALMAR_MIN, ge=True))

    # Gate 3 — Max drawdown. Metrics use a non-negative absolute fraction;
    # abs() keeps older serialized results with negative drawdown values compatible.
    gates.append(_check("max_drawdown", abs(metrics.max_drawdown), _MAX_DD_MAX, ge=False))

    # Gate 4 — Completed trades
    gates.append(_check("completed_trades", float(metrics.completed_trades), float(_COMPLETED_TRADES_MIN), ge=True))

    # Gate 5 — Segment Sharpe IR std (consistency)
    segment_ir_std = _segment_sharpe_ir_std(result.segments)
    gates.append(_check("segment_sharpe_ir_std", segment_ir_std, _SEGMENT_IR_STD_MAX, ge=False))

    # Determine verdict
    blocking = [g.name for g in gates if not g.passed]

    return VerdictV1(
        strategy_id=strategy_id or result.strategy_name,
        run_id=result.run_id,
        recommended_state="candidate" if not blocking else "rejected",
        hard_gates=gates,
        blocking_issues=[f"{name} failed" for name in blocking],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check(name: str, value: float, threshold: float, *, ge: bool) -> HardGateResultV1:
    """Create a HardGateResultV1 for a single comparison.

    Parameters
    ----------
    ge:
        If True the gate passes when *value >= threshold*.
        If False the gate passes when *value <= threshold* (upper-bound check).
    """
    passed = value >= threshold if ge else value <= threshold
    direction = ">=" if ge else "<="
    return HardGateResultV1(
        name=name,
        passed=passed,
        value=value,
        threshold=threshold,
        note=f"{name}={value:.4f} ({direction} {threshold})",
    )


def _segment_sharpe_ir_std(segments: list[SegmentMetricV1]) -> float:
    """Compute the standard deviation of per-segment Sharpe values.

    Returns 0.0 when fewer than 2 segments are available (degenerate case —
    the gate is effectively skipped because 0.0 <= 0.5).
    """
    sharpes = [s.sharpe for s in segments]
    if len(sharpes) < 2:
        return 0.0
    return statistics.stdev(sharpes)
