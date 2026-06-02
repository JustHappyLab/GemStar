"""ResearchAnalyst — generates research tickets from market context.

CALLING SPEC:
    generate_tickets(regime, events, factor_health, pool_path, llm_client) -> list[ResearchTicketV1]

SIDE EFFECTS:
    Delegates text generation to the supplied LLMGenerate implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.llm.adapter import LLMGenerate
from src.llm.json_utils import loads_llm_json, response_snippet
from src.schemas.factor import FactorHealthReportV1, FactorPoolV1
from src.schemas.research import ResearchTicketV1
from src.schemas.signal import MarketRegimeV1, SignalEventV1

_SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent.parent / "skills" / "generate_tickets" / "prompt.txt").read_text(encoding="utf-8")
_MAX_EVENTS = 5
_MAX_EVENT_SUMMARY_CHARS = 180
_MAX_HEALTH_ENTRIES = 12
_MAX_FACTOR_NAMES = 40


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
    # 1. Load factor pool first so the LLM sees a compact allow-list.
    pool = FactorPoolV1.load(pool_path)
    factor_names = [entry.name for entry in pool.all_entries()]

    # 2. Build compact context text.
    regime_line = (
        f"市场状态: {regime.regime}, 置信度: {regime.confidence}, "
        f"风格偏好: {regime.style_bias}"
    )
    event_lines = "\n".join(
        _event_line(e) for e in events[:_MAX_EVENTS]
    )

    factor_line = ", ".join(factor_names[:_MAX_FACTOR_NAMES])
    if len(factor_names) > _MAX_FACTOR_NAMES:
        factor_line += f", ... ({len(factor_names)} total)"

    parts = [
        regime_line,
        "",
        "可引用因子池:",
        factor_line or "(无)",
        "",
        "近期事件:",
        event_lines or "(无)",
    ]

    if factor_health is not None:
        health_lines = "\n".join(
            f"- {entry.factor_name}: {entry.status} "
            f"(IC_IR={entry.ic_ir}, IC_mean={entry.ic_mean}, coverage={entry.coverage})"
            for entry in factor_health.entries[:_MAX_HEALTH_ENTRIES]
        )
        parts.extend(["", "因子健康状态:", health_lines or "(无数据)"])

    user_prompt = "\n".join(parts)

    # 3. Load system prompt
    system_prompt = _SYSTEM_PROMPT

    # 4. Call LLM
    raw = llm_client.generate(user_prompt, system=system_prompt)

    # 5. Parse JSON response and validate.
    try:
        data = loads_llm_json(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "research_analyst returned invalid JSON: "
            f"{response_snippet(raw)}"
        ) from exc
    if not isinstance(data, list):
        raise ValueError("research_analyst must return a JSON array")
    tickets = [ResearchTicketV1.model_validate(item) for item in data]

    # 6. Filter out tickets referencing unregistered factors
    return [
        t for t in tickets
        if all(pool.is_registered(f) for f in t.affected_factors)
    ]


def _event_line(event: SignalEventV1) -> str:
    summary = _truncate(" ".join(event.summary.split()), _MAX_EVENT_SUMMARY_CHARS)
    return (
        f"- id={event.event_id}; type={event.event_type}; "
        f"severity={event.severity}; summary={summary}"
    )


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."
