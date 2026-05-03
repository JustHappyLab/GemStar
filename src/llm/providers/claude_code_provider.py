"""ClaudeCodeProvider — wraps the Claude Code CLI as an AgentProvider.

CALLING SPEC:
    ClaudeCodeProvider(model="sonnet", permission_mode="auto", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `claude`.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time

from src.llm.providers.base import AgentProvider, AgentResult

logger = logging.getLogger(__name__)


class ClaudeCodeProvider(AgentProvider):
    """Runs tasks via the `claude` CLI in non-interactive mode."""

    def __init__(
        self,
        model: str = "sonnet",
        permission_mode: str = "auto",
        timeout: int = 300,
    ) -> None:
        self._model = model
        self._permission_mode = permission_mode
        self._timeout = timeout

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Spawn `claude` CLI and parse JSON output."""
        system = (context or {}).get("system", "")
        full_prompt = f"{system}\n\n{task}" if system else task

        cmd = [
            "claude",
            "--model", self._model,
            "--permission-mode", self._permission_mode,
            "--output-format", "json",
            "--prompt", full_prompt,
        ]

        start = time.monotonic()
        logger.info("ClaudeCode: executing task (%d chars)", len(full_prompt))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {result.returncode}: {result.stderr}"
            )

        try:
            data = json.loads(result.stdout)
            output = data.get("result", result.stdout)
        except json.JSONDecodeError:
            output = result.stdout

        return AgentResult(
            output=output,
            duration_seconds=elapsed,
            provider="claude_code",
        )
