"""CodexCliProvider — wraps the Codex CLI as an AgentProvider.

CALLING SPEC:
    CodexCliProvider(model="o4-mini", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `codex`.
"""

from __future__ import annotations

from src.llm.providers.base import BaseCliProvider


class CodexCliProvider(BaseCliProvider):
    """Runs tasks via the `codex` CLI in non-interactive mode."""

    def __init__(self, model: str = "o4-mini", timeout: int = 300) -> None:
        super().__init__(provider_name="codex_cli", timeout=timeout)
        self._model = model

    def build_command(self, full_prompt: str) -> list[str]:
        return [
            "codex",
            "--model", self._model,
            "--quiet",
            full_prompt,
        ]
