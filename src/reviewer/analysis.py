"""Reviewer — LLM-generated verdict explanation.

CALLING SPEC:
    review_verdict(result, verdict, factor_health, llm_client) -> ReviewNotesV1

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via llm_client).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.llm.client import LLMClient
from src.schemas.factor import FactorHealthReportV1
from src.schemas.metrics import BacktestResultV1
from src.schemas.review import ReviewNotesV1
from src.schemas.verdict import VerdictV1

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "reviewer.txt"


def review_verdict(
    result: BacktestResultV1,
    verdict: VerdictV1,
    factor_health: FactorHealthReportV1 | None,
    llm_client: LLMClient,
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
    system_prompt = _PROMPT_PATH.read_text()

    response = llm_client.generate(user_prompt, system=system_prompt)

    # Validate and parse — ValueError propagates to LLMClient retry loop.
    return ReviewNotesV1.model_validate_json(response)
