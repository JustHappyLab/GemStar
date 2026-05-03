"""CodexCliProvider — wraps the Codex CLI as an AgentProvider.

CALLING SPEC:
    CodexCliProvider(model="o4-mini", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `codex`.
"""

from __future__ import annotations

import logging
import subprocess
import time

from src.llm.providers.base import AgentProvider, AgentResult

logger = logging.getLogger(__name__)


class CodexCliProvider(AgentProvider):
    """Runs tasks via the `codex` CLI in non-interactive mode."""

    def __init__(
        self,
        model: str = "o4-mini",
        timeout: int = 300,
    ) -> None:
        self._model = model
        self._timeout = timeout

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Spawn `codex` CLI and return raw output."""
        system = (context or {}).get("system", "")
        full_prompt = f"{system}\n\n{task}" if system else task

        cmd = [
            "codex",
            "--model", self._model,
            "--quiet",
            full_prompt,
        ]

        start = time.monotonic()
        logger.info("CodexCli: executing task (%d chars)", len(full_prompt))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            raise RuntimeError(
                f"codex CLI exited {result.returncode}: {result.stderr}"
            )

        return AgentResult(
            output=result.stdout.strip(),
            duration_seconds=elapsed,
            provider="codex_cli",
        )
