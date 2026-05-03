"""GeminiCliProvider — wraps the Gemini CLI as an AgentProvider.

CALLING SPEC:
    GeminiCliProvider(model="gemini-2.5-pro", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `gemini`.
"""

from __future__ import annotations

from src.llm.providers.base import BaseCliProvider


class GeminiCliProvider(BaseCliProvider):
    """Runs tasks via the `gemini` CLI in non-interactive mode."""

    def __init__(self, model: str = "gemini-2.5-pro", timeout: int = 300) -> None:
        super().__init__(provider_name="gemini_cli", timeout=timeout)
        self._model = model

    def build_command(self, full_prompt: str) -> list[str]:
        return [
            "gemini",
            "--model", self._model,
            "--prompt", full_prompt,
        ]
