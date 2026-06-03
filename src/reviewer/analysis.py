"""Reviewer — LLM-generated verdict explanation.

CALLING SPEC:
    review_verdict(result, verdict, factor_health, llm_client) -> ReviewNotesV1

SIDE EFFECTS:
    Delegates text generation to the supplied LLMGenerate implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.llm.adapter import LLMGenerate
from src.llm.json_utils import loads_llm_json
from src.schemas.factor import FactorHealthReportV1
from src.schemas.metrics import BacktestResultV1
from src.schemas.review import ReviewNotesV1
from src.schemas.verdict import VerdictV1

_SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent.parent / "role_skills" / "review_verdict" / "prompt.txt").read_text()


def review_verdict(
    result: BacktestResultV1,
    verdict: VerdictV1,
    factor_health: FactorHealthReportV1 | None,
    llm_client: LLMGenerate,
) -> ReviewNotesV1:
    """Generate LLM review notes for a strategy verdict.

    Args:
        result: Backtest output with metrics and segments.
        verdict: RuleJudge verdict with gate results.
        factor_health: Optional factor health report.
        llm_client: LLM client for API calls.

    Returns:
        ReviewNotesV1 with explanation, risks, and confidence.

    Raises:
        ValueError: If the LLM response cannot be parsed as ReviewNotesV1.
    """
    # Build context dict for the LLM prompt.
    context: dict = {
        "verdict": verdict.model_dump(),
        "metrics": {
            "sharpe": result.metrics.sharpe,
            "calmar": result.metrics.calmar,
            "max_drawdown": result.metrics.max_drawdown,
            "cagr": result.metrics.cagr,
            "win_rate": result.metrics.win_rate,
            "completed_trades": result.metrics.completed_trades,
        },
        "segments": [
            {
                "segment": seg.segment,
                "sharpe": seg.sharpe,
                "max_drawdown": seg.max_drawdown,
            }
            for seg in result.segments
        ],
    }

    if factor_health is not None:
        context["factor_health"] = [
            {
                "factor_name": entry.factor_name,
                "status": entry.status,
                "ic_ir": entry.ic_ir,
            }
            for entry in factor_health.entries
        ]

    user_prompt = json.dumps(context, ensure_ascii=False)
    system_prompt = _SYSTEM_PROMPT

    response = llm_client.generate(user_prompt, system=system_prompt)

    # Validate and parse — ValueError propagates to LLMGenerate retry loop.
    return ReviewNotesV1.model_validate(loads_llm_json(response))
