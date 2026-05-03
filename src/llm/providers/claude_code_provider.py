"""ClaudeCodeProvider — wraps the Claude Code CLI as an AgentProvider.

CALLING SPEC:
    ClaudeCodeProvider(model="sonnet", permission_mode="auto", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `claude`.
"""

from __future__ import annotations

import json

from src.llm.providers.base import BaseCliProvider


class ClaudeCodeProvider(BaseCliProvider):
    """Runs tasks via the `claude` CLI in non-interactive mode."""

    def __init__(
        self,
        model: str = "sonnet",
        permission_mode: str = "auto",
        timeout: int = 300,
    ) -> None:
        super().__init__(provider_name="claude_code", timeout=timeout)
        self._model = model
        self._permission_mode = permission_mode

    def build_command(self, full_prompt: str) -> list[str]:
        return [
            "claude",
            "--model", self._model,
            "--permission-mode", self._permission_mode,
            "--output-format", "json",
            "--prompt", full_prompt,
        ]

    def parse_output(self, stdout: str) -> str:
        try:
            data = json.loads(stdout)
            return data.get("result", stdout)
        except json.JSONDecodeError:
            return stdout
