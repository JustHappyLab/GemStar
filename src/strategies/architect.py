"""StrategyArchitect — drafts new strategy YAMLs from research tickets.

CALLING SPEC:
    draft_strategy(tickets, pool_path, reference_date, llm_client, output_dir) -> Path

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via llm_client).
    Writes a YAML file to output_dir.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.factors.pool import FactorPoolV1
from src.llm.client import LLMClient
from src.schemas.research import ResearchTicketV1
from src.schemas.strategy import StrategyConfigV1

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "strategy_architect.txt"


def _build_user_prompt(
    tickets: list[ResearchTicketV1],
    pool: FactorPoolV1,
    reference_date: str,
) -> str:
    """Assemble the user prompt from tickets, pool, and date context."""
    factors_block = "\n".join(
        f"- {e.name} ({e.source})" for e in pool.active
    )
    tickets_block = "\n".join(
        f"- [{t.ticket_type}] {t.hypothesis} (confidence: {t.confidence})"
        for t in tickets
    ) or "(no tickets — produce a baseline strategy)"

    return (
        f"## Reference date\n{reference_date}\n\n"
        f"## Active factor pool\n{factors_block}\n\n"
        f"## Research tickets\n{tickets_block}\n\n"
        f"## Backtest period hint\nstart: 20220101, end: {reference_date.replace('-', '')}"
    )


def draft_strategy(
    tickets: list[ResearchTicketV1],
    pool_path: Path,
    reference_date: str,
    llm_client: LLMClient,
    output_dir: str | Path = "strategies/drafts",
) -> Path:
    """Draft a new strategy YAML from research tickets.

    Args:
        tickets: Research tickets to base the strategy on.
        pool_path: Path to the factor pool JSON file.
        reference_date: Date string (YYYY-MM-DD) for context.
        llm_client: LLM client instance for generation.
        output_dir: Directory to write the draft YAML.

    Returns:
        Path to the written YAML file.

    Raises:
        ValueError: If the LLM response cannot be parsed or validated.
    """
    pool = FactorPoolV1.load(pool_path)
    user_prompt = _build_user_prompt(tickets, pool, reference_date)
    system_prompt = _PROMPT_PATH.read_text()

    response = llm_client.generate(user_prompt, system=system_prompt)
    try:
        yaml_data = yaml.safe_load(response)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse YAML response: {exc}") from exc
    config = StrategyConfigV1.model_validate(yaml_data)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{config.name}_{reference_date}.yaml"
    dest = out / filename
    dest.write_text(yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False))
    return dest
