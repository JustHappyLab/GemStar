"""Reviewer LLM role — generates ReviewNotesV1 for each verdict.

CALLING SPEC:
    notes = review_verdict(bt_result, verdict, factor_health, llm) -> ReviewNotesV1

    Sends backtest results + verdict + factor health context to the LLM,
    asks it to explain the verdict and highlight risks.  Best-effort:
    callers should catch exceptions and skip failed reviews.

SIDE EFFECTS:
    Makes an LLM API call via the provided LLMClient.
"""

from __future__ import annotations

from src.llm.client import LLMClient
from src.schemas.factor import FactorHealthReportV1
from src.schemas.metrics import BacktestResultV1
from src.schemas.review import ReviewNotesV1
from src.schemas.verdict import VerdictV1

import json


def review_verdict(
    bt_result: BacktestResultV1,
    verdict: VerdictV1,
    factor_health: FactorHealthReportV1 | None,
    llm: LLMClient,
) -> ReviewNotesV1:
    """Generate LLM review notes for a verdict.

    Parameters
    ----------
    bt_result : BacktestResultV1
        Backtest metrics for the strategy.
    verdict : VerdictV1
        RuleJudge verdict to review.
    factor_health : FactorHealthReportV1 | None
        Factor health context; may be None.
    llm : LLMClient
        LLM client for generation.

    Returns
    -------
    ReviewNotesV1
        LLM-generated review explanation.
    """
    factor_summary = ""
    if factor_health:
        factor_summary = "\n".join(
            f"  - {e.factor_name}: status={e.status}, IC_IR={e.ic_ir}"
            for e in factor_health.entries
        )

    gates_summary = "\n".join(
        f"  - {g.name}: {'PASS' if g.passed else 'FAIL'} "
        f"(value={g.value}, threshold={g.threshold})"
        for g in verdict.hard_gates
    )

    prompt = f"""You are a quantitative strategy reviewer. Given the backtest result and verdict below, explain the verdict and highlight any risks.

## Backtest Result
- Strategy: {bt_result.strategy_name}
- Sharpe: {bt_result.metrics.sharpe}
- CAGR: {bt_result.metrics.cagr}
- Max Drawdown: {bt_result.metrics.max_drawdown}
- Alpha: {bt_result.metrics.alpha}

## Verdict
- Recommended state: {verdict.recommended_state}
- Hard gates:
{gates_summary}
- Blocking issues: {verdict.blocking_issues}
- Warnings: {verdict.warnings}

## Factor Health
{factor_summary if factor_summary else "N/A"}

Respond with a JSON object matching this schema:
{{
  "version": "ReviewNotesV1",
  "strategy_id": "{verdict.strategy_id}",
  "run_id": "{verdict.run_id}",
  "verdict_summary": "<one-line summary>",
  "explanation": "<detailed explanation in Chinese>",
  "risk_highlights": ["<risk1>", ...],
  "confidence": <0.0-1.0>
}}
"""

    raw = llm.generate(prompt)
    data = json.loads(raw)
    return ReviewNotesV1(**data)
