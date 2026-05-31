"""Small LLM test doubles for offline tests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.llm.providers.base import AgentResult


@dataclass
class FakeLLM:
    """Minimal object satisfying the LLMGenerate protocol."""

    responses: list[str]
    calls: list[dict[str, str | None]] = field(default_factory=list)
    _index: int = 0

    def __init__(self, responses: str | Iterable[str]) -> None:
        if isinstance(responses, str):
            self.responses = [responses]
        else:
            self.responses = list(responses)
        self.calls = []
        self._index = 0

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        if not self.responses:
            raise AssertionError("FakeLLM has no responses configured")
        index = min(self._index, len(self.responses) - 1)
        self._index += 1
        return self.responses[index]


class FakeRoleRegistry:
    """RoleRegistry-like fake that returns configured text per role."""

    def __init__(self, responses_by_role: dict[str, str | Iterable[str]]) -> None:
        self._responses: dict[str, list[str]] = {}
        for role, responses in responses_by_role.items():
            if isinstance(responses, str):
                self._responses[role] = [responses]
            else:
                self._responses[role] = list(responses)
        self._indices: defaultdict[str, int] = defaultdict(int)
        self.calls: list[dict[str, object]] = []

    def list_roles(self) -> list[str]:
        return sorted(self._responses)

    def execute_role(self, name: str, context: dict | None = None) -> AgentResult:
        self.calls.append({"role": name, "context": context})
        responses = self._responses.get(name)
        if not responses:
            raise KeyError(f"No fake response configured for role: {name}")
        index = min(self._indices[name], len(responses) - 1)
        self._indices[name] += 1
        return AgentResult(output=responses[index], provider="claude_code")
