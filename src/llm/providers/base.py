"""AgentProvider — abstract interface for LLM agent execution.

CALLING SPEC:
    AgentProvider.execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    None — ABC only.
"""

from __future__ import annotations

import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Unified result from any agent provider."""

    output: str
    artifacts: list[Path] = field(default_factory=list)
    token_usage: int = 0
    duration_seconds: float = 0.0
    provider: str = ""


class AgentProvider(ABC):
    """Abstract base for all agent execution providers."""

    @abstractmethod
    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Execute a task and return the result."""
        ...


class BaseCliProvider(AgentProvider):
    """Base for CLI subprocess providers. Subclasses override build_command()."""

    def __init__(self, provider_name: str, timeout: int = 300) -> None:
        self._provider_name = provider_name
        self._timeout = timeout

    @abstractmethod
    def build_command(self, full_prompt: str) -> list[str]:
        """Build the CLI command list for the given prompt."""
        ...

    def parse_output(self, stdout: str) -> str:
        """Parse CLI stdout into the final output string. Override for JSON parsing."""
        return stdout.strip()

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        """Spawn CLI subprocess and return the result."""
        system = (context or {}).get("system", "")
        full_prompt = f"{system}\n\n{task}" if system else task

        cmd = self.build_command(full_prompt)
        start = time.monotonic()
        logger.info("%s: executing task (%d chars)", self._provider_name, len(full_prompt))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        elapsed = time.monotonic() - start

        if result.returncode != 0:
            raise RuntimeError(
                f"{self._provider_name} exited {result.returncode}: {result.stderr}"
            )

        return AgentResult(
            output=self.parse_output(result.stdout),
            duration_seconds=elapsed,
            provider=self._provider_name,
        )
