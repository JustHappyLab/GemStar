"""Tests for the LLMGenerate protocol adapter."""

from __future__ import annotations

import pytest

from src.llm.adapter import RoleLLMAdapter
from src.llm.providers.base import AgentResult


class StubRegistry:
    def __init__(self, output: str = "role ok", side_effect: BaseException | None = None):
        self.output = output
        self.side_effect = side_effect
        self.last_role: str | None = None
        self.last_context: dict | None = None

    def execute_role(self, name: str, context: dict | None = None) -> AgentResult:
        if self.side_effect is not None:
            raise self.side_effect
        self.last_role = name
        self.last_context = context
        return AgentResult(output=self.output, provider="claude_code")


def test_role_adapter_executes_named_role() -> None:
    registry = StubRegistry(output="role result")
    adapter = RoleLLMAdapter(registry, "reviewer")

    result = adapter.generate("review this", system="ignored by role adapter")

    assert result == "role result"
    assert registry.last_role == "reviewer"
    assert registry.last_context == {"task": "review this"}


def test_role_adapter_preserves_exact_output() -> None:
    exact = "  line1\nline2\ttab  "
    adapter = RoleLLMAdapter(StubRegistry(output=exact), "macro_analyst")

    assert adapter.generate("prompt") is exact


def test_role_adapter_propagates_registry_exception() -> None:
    adapter = RoleLLMAdapter(StubRegistry(side_effect=RuntimeError("boom")), "reviewer")

    with pytest.raises(RuntimeError, match="boom"):
        adapter.generate("prompt")
