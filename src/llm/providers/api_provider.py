"""APIProvider — direct Anthropic SDK wrapper implementing AgentProvider.

CALLING SPEC:
    APIProvider(model="claude-sonnet-4-20250514", max_retries=3, api_key=None)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import anthropic

from src.llm.providers.base import AgentProvider, AgentResult

logger = logging.getLogger(__name__)

_FORBIDDEN_KWARGS = frozenset({"tools", "tool_choice"})


class APIProvider(AgentProvider):
    """Anthropic Messages API provider — single-shot text generation."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._client = anthropic.Anthropic(api_key=api_key)

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Send task to Anthropic API and return the text response."""
        system = (context or {}).get("system")
        start = time.monotonic()
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": task}],
                }
                if system is not None:
                    kwargs["system"] = system

                violations = _FORBIDDEN_KWARGS & set(kwargs)
                if violations:
                    raise RuntimeError(f"Forbidden kwargs detected: {violations}")

                response = self._client.messages.create(**kwargs)

                for block in response.content:
                    if block.type == "text":
                        elapsed = time.monotonic() - start
                        return AgentResult(
                            output=block.text,
                            token_usage=response.usage.input_tokens
                            + response.usage.output_tokens,
                            duration_seconds=elapsed,
                            provider="api",
                        )

                raise ValueError("Response contained no text blocks")

            except (ValueError, KeyError) as exc:
                last_exc = exc
                logger.warning(
                    "Attempt %d/%d failed: %s", attempt, self._max_retries, exc
                )
                continue

        raise ValueError(
            f"Failed after {self._max_retries} retries: {last_exc}"
        ) from last_exc
