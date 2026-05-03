"""APIProvider — wraps LLMClient as an AgentProvider.

CALLING SPEC:
    APIProvider(model="claude-sonnet-4-20250514", max_retries=3, api_key=None)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via LLMClient).
"""

from __future__ import annotations

import time

from src.llm.client import LLMClient
from src.llm.providers.base import AgentProvider, AgentResult


class APIProvider(AgentProvider):
    """Anthropic Messages API provider — delegates to LLMClient."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._client = LLMClient(model=model, max_retries=max_retries, api_key=api_key, base_url=base_url)

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Send task to Anthropic API via LLMClient and wrap the result."""
        system = (context or {}).get("system")
        start = time.monotonic()
        output = self._client.generate(task, system=system)
        elapsed = time.monotonic() - start

        return AgentResult(
            output=output,
            duration_seconds=elapsed,
            provider="api",
        )
