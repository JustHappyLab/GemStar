"""GeminiCliProvider — wraps the Gemini CLI as an AgentProvider.

CALLING SPEC:
    GeminiCliProvider(model="gemini-2.5-pro", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `gemini`.
"""

from __future__ import annotations

import logging
import subprocess
import time

from src.llm.providers.base import AgentProvider, AgentResult

logger = logging.getLogger(__name__)


class GeminiCliProvider(AgentProvider):
    """Runs tasks via the `gemini` CLI in non-interactive mode."""

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        timeout: int = 300,
    ) -> None:
        self._model = model
        self._timeout = timeout

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Spawn `gemini` CLI and return raw output."""
        system = (context or {}).get("system", "")
        full_prompt = f"{system}\n\n{task}" if system else task

        cmd = [
            "gemini",
            "--model", self._model,
            "--prompt", full_prompt,
        ]

        start = time.monotonic()
        logger.info("GeminiCli: executing task (%d chars)", len(full_prompt))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            raise RuntimeError(
                f"gemini CLI exited {result.returncode}: {result.stderr}"
            )

        return AgentResult(
            output=result.stdout.strip(),
            duration_seconds=elapsed,
            provider="gemini_cli",
        )
