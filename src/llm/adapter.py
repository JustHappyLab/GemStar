"""RoleLLMAdapter — adapts RoleRegistry to a standard generate() interface.

CALLING SPEC:
    RoleLLMAdapter(registry, role_name)
        .generate(prompt, system=None) -> str

SIDE EFFECTS:
    Delegates to registry.execute_role().
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.roles.registry import RoleRegistry


class LLMGenerate(Protocol):
    """Protocol for any callable that can generate text from a prompt.

    Both RoleLLMAdapter and test mocks satisfy this interface.
    """
    def generate(self, prompt: str, system: str | None = None) -> str: ...


class RoleLLMAdapter:
    """Adapts a RoleRegistry role to the LLMGenerate interface."""

    def __init__(self, registry: RoleRegistry, role_name: str) -> None:
        self._registry = registry
        self._role_name = role_name

    def generate(self, prompt: str, system: str | None = None) -> str:
        context = {"task": prompt}
        if system:
            context["system"] = system
        result = self._registry.execute_role(self._role_name, context)
        return result.output
