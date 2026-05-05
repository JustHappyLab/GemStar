"""LLMAdapter — wraps AgentProvider to match LLMClient.generate() interface.

CALLING SPEC:
    LLMAdapter(provider: AgentProvider)
        .generate(prompt, system=None) -> str

SIDE EFFECTS:
    Delegates to provider.execute().
"""

from __future__ import annotations

from src.llm.providers.base import AgentProvider
from src.roles.registry import RoleRegistry


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


class RoleLLMAdapter:
    """Adapts a configured RoleRegistry role to the LLMClient.generate() interface."""

    def __init__(self, registry: RoleRegistry, role_name: str) -> None:
        self._registry = registry
        self._role_name = role_name

    def generate(self, prompt: str, system: str | None = None) -> str:
        # The registry composes the role's skill prompts.  The system argument is
        # accepted for interface compatibility with modules that also run with a
        # direct LLMClient in tests.
        result = self._registry.execute_role(self._role_name, {"task": prompt})
        return result.output
