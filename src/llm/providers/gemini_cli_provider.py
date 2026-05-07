"""GeminiCliProvider — wraps the Gemini CLI as an AgentProvider.

CALLING SPEC:
    GeminiCliProvider(model="gemini-2.5-pro", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `gemini`.
"""

from __future__ import annotations

import json
import re

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
            "--output-format", "json",
            "--prompt", full_prompt,
        ]

    def parse_output(self, stdout: str) -> str:
        # --output-format json returns an object with a "result" field
        try:
            data = json.loads(stdout)
            return data.get("result", stdout)
        except json.JSONDecodeError:
            pass
        # Fallback: strip markdown code fences from text-mode output
        m = re.search(r"```(?:json)?\s*\n(.*?)\n```", stdout.strip(), re.DOTALL)
        return m.group(1).strip() if m else stdout.strip()
