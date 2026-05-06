"""CodexCliProvider — wraps the Codex CLI as an AgentProvider.

CALLING SPEC:
    CodexCliProvider(model="o4-mini", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `codex`.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from src.llm.providers.base import AgentResult, BaseCliProvider


class CodexCliProvider(BaseCliProvider):
    """Runs tasks via the `codex` CLI in non-interactive mode."""

    def __init__(self, model: str | None = None, timeout: int = 300) -> None:
        super().__init__(provider_name="codex_cli", timeout=timeout)
        self._model = model

    def build_command(self, full_prompt: str, output_path: str | None = None) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--color", "never",
        ]
        if self._model:
            cmd.extend(["--model", self._model])
        if output_path:
            cmd.extend(["--output-last-message", output_path])
        cmd.append(full_prompt)
        return cmd

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Run Codex and return only the final assistant message."""
        system = (context or {}).get("system", "")
        full_prompt = f"{system}\n\n{task}" if system else task

        output_file = tempfile.NamedTemporaryFile(prefix="gemstar-codex-", suffix=".txt", delete=False)
        output_path = Path(output_file.name)
        output_file.close()

        start = time.monotonic()
        try:
            result = subprocess.run(
                self.build_command(full_prompt, str(output_path)),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            elapsed = time.monotonic() - start

            if result.returncode != 0:
                raise RuntimeError(f"codex_cli exited {result.returncode}: {result.stderr}")

            output = output_path.read_text().strip()
            if not output:
                output = self.parse_output(result.stdout)

            return AgentResult(
                output=output,
                duration_seconds=elapsed,
                provider="codex_cli",
            )
        finally:
            output_path.unlink(missing_ok=True)
