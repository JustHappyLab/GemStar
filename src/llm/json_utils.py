"""Utilities for parsing JSON returned by LLM providers."""

from __future__ import annotations

import json
import re
from typing import Any


def strip_json_fence(text: str) -> str:
    """Remove a full-response markdown JSON fence if one is present."""
    s = text.strip()
    return re.sub(r"^```(?:json)?\s*", "", re.sub(r"\s*```$", "", s))


def loads_llm_json(text: str) -> Any:
    """Parse JSON from an LLM response, accepting light prose around it."""
    cleaned = strip_json_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as original_exc:
        decoder = json.JSONDecoder()
        for start, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[start:])
            except json.JSONDecodeError:
                continue
            return value
        raise original_exc


def response_snippet(text: str, max_chars: int = 500) -> str:
    """Return a compact diagnostic snippet without dumping long prompts/logs."""
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."
