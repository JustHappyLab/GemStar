"""AgentProvider — abstract interface for LLM agent execution.

CALLING SPEC:
    AgentProvider.execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    None — ABC only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


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
