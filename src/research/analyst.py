"""ResearchAnalyst — generates research tickets from market context.

CALLING SPEC:
    generate_tickets(regime, events, factor_health, pool_path, llm_client) -> list[ResearchTicketV1]

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via llm_client).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.llm.adapter import LLMGenerate
from src.schemas.factor import FactorHealthReportV1, FactorPoolV1
from src.schemas.research import ResearchTicketV1
from src.schemas.signal import MarketRegimeV1, SignalEventV1

_SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent.parent / "skills" / "generate_tickets" / "prompt.txt").read_text(encoding="utf-8")


def generate_tickets(
    regime: MarketRegimeV1,
    events: list[SignalEventV1],
    factor_health: FactorHealthReportV1 | None,
    pool_path: Path,
    llm_client: LLMGenerate,
) -> list[ResearchTicketV1]:
    """Generate research tickets from market context via LLM.

    Args:
        regime: Current market regime assessment.
        events: Recent signal events.
        factor_health: Optional factor health report.
        pool_path: Path to factor pool JSON file.
        llm_client: LLM client for API calls.

    Returns:
        Validated list of ResearchTicketV1 objects with known factors only.
    """
    # 1. Build context text
    regime_line = (
        f"市场状态: {regime.regime}, 置信度: {regime.confidence}, "
        f"风格偏好: {regime.style_bias}"
    )
    event_lines = "\n".join(
        f"- [{e.event_type}] {e.summary}" for e in events
    )

    parts = [regime_line, "", "近期事件:", event_lines or "(无)"]

    if factor_health is not None:
        health_lines = "\n".join(
            f"- {entry.factor_name}: {entry.status} (IC_IR={entry.ic_ir})"
            for entry in factor_health.entries
        )
        parts.extend(["", "因子健康状态:", health_lines or "(无数据)"])

    user_prompt = "\n".join(parts)

    # 2. Load system prompt
    system_prompt = _SYSTEM_PROMPT

    # 3. Call LLM
    raw = llm_client.generate(user_prompt, system=system_prompt)

    # 4. Parse JSON response (strip markdown fences if present) and validate
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    tickets = [ResearchTicketV1.model_validate(item) for item in data]

    # 5. Load factor pool
    pool = FactorPoolV1.load(pool_path)

    # 6. Filter out tickets referencing unregistered factors
    return [
        t for t in tickets
        if all(pool.is_registered(f) for f in t.affected_factors)
    ]
