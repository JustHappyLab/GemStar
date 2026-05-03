"""LLMAdapter — wraps AgentProvider to match LLMClient.generate() interface.

CALLING SPEC:
    LLMAdapter(provider: AgentProvider)
        .generate(prompt, system=None) -> str

SIDE EFFECTS:
    Delegates to provider.execute().
"""

from __future__ import annotations

from src.llm.providers.base import AgentProvider


class LLMAdapter:
    """Adapts AgentProvider to the LLMClient.generate() interface.

    This allows existing modules (macro_analyst, event_scanner, etc.)
    to work with any provider without code changes.
    """

    def __init__(self, provider: AgentProvider) -> None:
        self._provider = provider

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate a text response, matching LLMClient.generate() signature."""
        context = {"system": system} if system else None
        result = self._provider.execute(prompt, context=context)
        return result.output
