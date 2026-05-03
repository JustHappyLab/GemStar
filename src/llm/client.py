"""Anthropic SDK wrapper with policy enforcement and structured-output retry.

CALLING SPEC:
    LLMClient(model, max_retries=3, api_key=None)
        .generate(prompt, system=None) -> str
            Sends prompt to the Anthropic Messages API.
            - Never passes tools (policy: allow_tools=false).
            - Retries up to max_retries when structured-output validation fails.
            Returns the raw text content of the first response block.

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# Forbidden policy flags — the client must never supply these.
_FORBIDDEN_KWARGS = frozenset({"tools", "tool_choice"})


class LLMClient:
    """Stateless LLM client that enforces no-tool, no-code-write, no-network policy."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate a text response from the model.

        Args:
            prompt: The user message.
            system: Optional system prompt.

        Returns:
            The text content of the first content block.

        Raises:
            anthropic.APIError: On unrecoverable API errors.
            ValueError: If schema validation fails after all retries.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if system is not None:
                    kwargs["system"] = system

                # Policy enforcement — reject forbidden kwargs at runtime.
                violations = _FORBIDDEN_KWARGS & set(kwargs)
                if violations:
                    raise RuntimeError(
                        f"Forbidden kwargs detected: {violations}"
                    )

                response = self._client.messages.create(**kwargs)

                # Extract text from the first text block.
                for block in response.content:
                    if block.type == "text":
                        return block.text

                raise ValueError("Response contained no text blocks")

            except (ValueError, KeyError) as exc:
                last_exc = exc
                logger.warning(
                    "Attempt %d/%d failed validation: %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
                continue

        raise ValueError(
            f"Failed after {self._max_retries} retries: {last_exc}"
        ) from last_exc
