"""StrategyArchitect — drafts new strategy YAMLs from research tickets.

CALLING SPEC:
    draft_strategy(tickets, pool_path, reference_date, llm_client, output_dir) -> Path

SIDE EFFECTS:
    Delegates text generation to the supplied LLMGenerate implementation.
    Writes a YAML file to output_dir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.factors.pool import FactorPoolV1
from src.llm.adapter import LLMGenerate
from src.schemas.research import ResearchTicketV1
from src.schemas.strategy import StrategyConfigV1

_SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent.parent / "skills" / "draft_strategy" / "prompt.txt").read_text()
_UNIVERSE_ALIASES = {
    "a_share_full": "a_share",
    "full_a_share": "a_share",
    "all_a_share": "a_share",
    "gemstar_default": "auto",
}


def _strip_yaml_fence(response: str) -> str:
    """Return raw YAML when the LLM wraps it in a markdown code fence."""
    text = response.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _extract_yaml_document(response: str) -> str:
    """Extract the strategy YAML body from common prose-wrapped LLM responses."""
    text = _strip_yaml_fence(response)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "version: StrategyConfigV1":
            return "\n".join(lines[index:]).strip()
    return text


def _quote_yaml_scalar(value: str) -> str:
    """Quote a plain YAML scalar while preserving readable text."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _quote_known_text_fields(yaml_text: str) -> str:
    """Quote known one-line text fields that often contain colon-space prose."""
    text_fields = {"hypothesis", "source_idea", "universe_rationale"}
    quoted_lines: list[str] = []

    for line in yaml_text.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        key, separator, value = stripped.partition(":")
        value = value.strip()
        if (
            separator
            and key in text_fields
            and value
            and not value.startswith(("'", '"', "|", ">"))
        ):
            quoted_lines.append(f"{indent}{key}: {_quote_yaml_scalar(value)}")
            continue
        quoted_lines.append(line)

    return "\n".join(quoted_lines)


def _load_yaml_mapping(response: str) -> dict[str, Any]:
    """Parse an LLM response into a YAML mapping suitable for strategy validation."""
    yaml_text = _quote_known_text_fields(_extract_yaml_document(response))
    try:
        yaml_data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse YAML response: {exc}") from exc

    if not isinstance(yaml_data, dict):
        raise ValueError(f"Strategy draft must be a YAML mapping, got {type(yaml_data).__name__}")
    return yaml_data


def _truncate_for_retry(text: str, limit: int = 4000) -> str:
    """Keep repair prompts bounded when a provider returns verbose prose."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _build_repair_prompt(original_prompt: str, bad_response: str, error: Exception) -> str:
    """Ask the LLM to repair only the response shape after validation failure."""
    return (
        f"{original_prompt}\n\n"
        "## Previous strategy draft was rejected\n"
        f"Error: {error}\n\n"
        "Rewrite the previous answer as exactly one valid YAML mapping for "
        "StrategyConfigV1. Do not output markdown, bullet-list explanation, "
        "or prose. The first line must be exactly: "
        "version: StrategyConfigV1.\n\n"
        "## Previous answer\n"
        f"```text\n{_truncate_for_retry(bad_response)}\n```"
    )


def _as_positive_float(value: Any) -> float | None:
    """Convert a YAML scalar into a strictly positive factor weight."""
    if isinstance(value, bool):
        return None
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None
    if weight <= 0.0:
        return None
    return weight


def _normalize_factors(
    factors: Any,
    pool: FactorPoolV1,
) -> list[dict[str, float | str]]:
    """Keep only executable positive-weight factors from the active + candidate pool."""
    active_names = {entry.name for entry in pool.active}
    candidate_names = {entry.name for entry in pool.candidates if entry.expression}
    normalized: list[dict[str, float | str]] = []

    if not isinstance(factors, list):
        return normalized

    for item in factors:
        if not isinstance(item, dict):
            continue
        factor_id = item.get("factor_id")
        if factor_id not in active_names and factor_id not in candidate_names:
            continue
        weight = _as_positive_float(item.get("weight"))
        if weight is None:
            continue
        normalized.append({"factor_id": factor_id, "weight": weight})

    total = sum(float(item["weight"]) for item in normalized)
    if total <= 0.0:
        return []

    for item in normalized:
        item["weight"] = round(float(item["weight"]) / total, 6)
    return normalized


def _normalize_strategy_draft(
    yaml_data: dict[str, Any],
    pool: FactorPoolV1,
) -> dict[str, Any]:
    """Make common LLM draft mistakes schema-safe without inventing new factors."""
    normalized = dict(yaml_data)
    normalized["version"] = "StrategyConfigV1"

    universe = normalized.get("universe")
    if isinstance(universe, str):
        normalized["universe"] = _UNIVERSE_ALIASES.get(universe, universe)

    factors = _normalize_factors(normalized.get("factors"), pool)
    if not factors:
        raise ValueError(
            "Strategy draft contains no usable positive-weight factors from the active pool"
        )
    normalized["factors"] = factors
    return normalized


def _validate_strategy_draft(yaml_data: dict[str, Any]) -> StrategyConfigV1:
    """Validate draft data and raise a compact diagnostic on schema failure."""
    try:
        return StrategyConfigV1.model_validate(yaml_data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        raise ValueError(f"Strategy draft schema validation failed: {errors}") from exc


def _parse_strategy_response(
    response: str,
    pool: FactorPoolV1,
) -> tuple[dict[str, Any], StrategyConfigV1]:
    """Parse, normalize, and validate one LLM strategy response."""
    yaml_data = _load_yaml_mapping(response)
    yaml_data = _normalize_strategy_draft(yaml_data, pool)
    config = _validate_strategy_draft(yaml_data)
    return yaml_data, config


def _build_user_prompt(
    tickets: list[ResearchTicketV1],
    pool: FactorPoolV1,
    reference_date: str,
) -> str:
    """Assemble the user prompt from tickets, pool, and date context."""
    factors_block = "\n".join(
        f"- {e.name} ({e.source})" for e in pool.active
    )
    candidate_factors = [e for e in pool.candidates if e.expression]
    candidates_block = "\n".join(
        f"- {e.name}: {e.hypothesis or e.expression} (IC_IR={e.ic_ir:.2f})" if e.ic_ir is not None
        else f"- {e.name}: {e.hypothesis or e.expression}"
        for e in candidate_factors
    )
    tickets_block = "\n".join(
        f"- [{t.ticket_type}] {t.hypothesis} (confidence: {t.confidence})"
        for t in tickets
    ) or "(no tickets — produce a baseline strategy)"

    prompt = (
        f"## Reference date\n{reference_date}\n\n"
        f"## Active factor pool\n{factors_block}\n\n"
    )
    if candidates_block:
        prompt += f"## Candidate factors (newly mined, usable)\n{candidates_block}\n\n"
    prompt += (
        f"## Research tickets\n{tickets_block}\n\n"
        f"## Backtest period hint\nstart: 20220101, end: {reference_date.replace('-', '')}"
    )
    return prompt


def draft_strategy(
    tickets: list[ResearchTicketV1],
    pool_path: Path,
    reference_date: str,
    llm_client: LLMGenerate,
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
    system_prompt = _SYSTEM_PROMPT

    response = llm_client.generate(user_prompt, system=system_prompt)
    for attempt in range(2):
        try:
            yaml_data, config = _parse_strategy_response(response, pool)
            break
        except ValueError as exc:
            if attempt == 1:
                raise
            repair_prompt = _build_repair_prompt(user_prompt, response, exc)
            response = llm_client.generate(repair_prompt, system=system_prompt)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{config.name}_{reference_date}.yaml"
    dest = out / filename
    dest.write_text(yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False))
    return dest
