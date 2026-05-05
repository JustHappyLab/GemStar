"""Tests for LLMAdapter — wraps AgentProvider to match LLMClient.generate() interface."""

from __future__ import annotations

import pytest

from src.llm.adapter import LLMAdapter, RoleLLMAdapter
from src.llm.providers.base import AgentProvider, AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class StubProvider(AgentProvider):
    """Minimal concrete provider for testing."""

    def __init__(self, output: str = "", side_effect: BaseException | None = None):
        self._output = output
        self._side_effect = side_effect
        self.last_task: str | None = None
        self.last_context: dict | None = None

    def execute(self, task: str, context: dict | None = None) -> AgentResult:
        if self._side_effect is not None:
            raise self._side_effect
        self.last_task = task
        self.last_context = context
        return AgentResult(output=self._output)


class StubRegistry:
    def __init__(self, output: str = "role ok"):
        self.output = output
        self.last_role: str | None = None
        self.last_context: dict | None = None

    def execute_role(self, name: str, context: dict | None = None) -> AgentResult:
        self.last_role = name
        self.last_context = context
        return AgentResult(output=self.output)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_calls_provider_execute_and_returns_output():
    """generate(prompt) calls provider.execute(prompt, context=None) and returns result.output."""
    stub = StubProvider(output="hello world")
    adapter = LLMAdapter(stub)

    result = adapter.generate("my prompt")

    assert result == "hello world"
    assert stub.last_task == "my prompt"
    assert stub.last_context is None


def test_generate_with_system_passes_context():
    """generate(prompt, system='sys') passes context={'system': 'sys'} to provider."""
    stub = StubProvider(output="ok")
    adapter = LLMAdapter(stub)

    adapter.generate("my prompt", system="sys")

    assert stub.last_task == "my prompt"
    assert stub.last_context == {"system": "sys"}


def test_provider_exception_propagates():
    """Exception raised by the provider propagates through LLMAdapter."""
    stub = StubProvider(side_effect=ValueError("boom"))
    adapter = LLMAdapter(stub)

    with pytest.raises(ValueError, match="boom"):
        adapter.generate("any prompt")


def test_empty_string_output():
    """Provider returning empty string yields empty string."""
    stub = StubProvider(output="")
    adapter = LLMAdapter(stub)

    result = adapter.generate("prompt")

    assert result == ""


def test_preserves_exact_output_string():
    """The exact output string from the provider is preserved, including whitespace."""
    exact = "  line1\nline2\ttab  "
    stub = StubProvider(output=exact)
    adapter = LLMAdapter(stub)

    result = adapter.generate("prompt")

    assert result is exact  # identity check, not just equality


def test_role_adapter_executes_named_role():
    registry = StubRegistry(output="role result")
    adapter = RoleLLMAdapter(registry, "reviewer")

    result = adapter.generate("review this", system="ignored by role adapter")

    assert result == "role result"
    assert registry.last_role == "reviewer"
    assert registry.last_context == {"task": "review this"}
