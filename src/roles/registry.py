"""RoleRegistry — loads role YAML configs, manages providers and skills.

CALLING SPEC:
    RoleRegistry(roles_dir="roles", skills_dir="skills")
        .execute_role(name, context) -> AgentResult
        .get_role(name) -> RoleConfig
        .get_provider(name) -> AgentProvider
        .list_roles() -> list[str]

SIDE EFFECTS:
    Reads YAML and text files from disk at init time.
    Executes LLM/provider calls via AgentProvider.execute().
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.llm.providers import (
    AgentProvider,
    AgentResult,
    APIProvider,
    ClaudeCodeProvider,
    CodexCliProvider,
    GeminiCliProvider,
)
from src.roles.config import RoleConfig
from src.roles.events import RoleEvent

logger = logging.getLogger(__name__)

_PROVIDER_MAP: dict[str, type[AgentProvider]] = {
    "api": APIProvider,
    "claude_code": ClaudeCodeProvider,
    "gemini_cli": GeminiCliProvider,
    "codex_cli": CodexCliProvider,
}


def _read_or_default(path: Path, default: str = "") -> str:
    """Read a file, returning default if it doesn't exist."""
    try:
        return path.read_text()
    except FileNotFoundError:
        return default


class SkillContent:
    """Loaded content of a single skill directory."""

    def __init__(self, name: str, skill_dir: Path) -> None:
        self.name = name
        self.sop = _read_or_default(skill_dir / "sop.md")
        self.prompt = _read_or_default(skill_dir / "prompt.txt")
        self.schema_ref: str | None = None
        schema_raw = _read_or_default(skill_dir / "schema.json")
        if schema_raw:
            try:
                self.schema_ref = json.loads(schema_raw).get("schema_ref")
            except json.JSONDecodeError:
                logger.warning("Malformed schema.json in skill '%s'", name)


class RoleRegistry:
    """Loads role YAML configs and executes them via the appropriate provider."""

    def __init__(
        self,
        roles_dir: str | Path = "roles",
        skills_dir: str | Path = "skills",
        event_callback: Callable[[RoleEvent], None] | None = None,
        overrides: dict[str, dict] | None = None,
    ) -> None:
        self._roles_dir = Path(roles_dir)
        self._skills_dir = Path(skills_dir)
        self._event_callback = event_callback
        self._roles: dict[str, RoleConfig] = {}
        self._skills: dict[str, SkillContent] = {}
        self._providers: dict[str, AgentProvider] = {}
        self._overrides = overrides or {}

        self._load_roles()
        self._apply_overrides()
        self._load_skills()

    def _load_roles(self) -> None:
        """Load all role YAML files from roles_dir."""
        if not self._roles_dir.exists():
            return
        for path in sorted(self._roles_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if data and "name" in data:
                config = RoleConfig(**data)
                self._roles[config.name] = config

    def _apply_overrides(self) -> None:
        """Apply gemstar.yaml role overrides to loaded role configs."""
        for role_name, override in self._overrides.items():
            if role_name in self._roles and "provider" in override:
                role = self._roles[role_name]
                self._roles[role_name] = role.model_copy(update={"provider": override["provider"]})

    def _load_skills(self) -> None:
        """Load all skill directories from skills_dir."""
        if not self._skills_dir.exists():
            return
        for path in sorted(self._skills_dir.iterdir()):
            if path.is_dir():
                self._skills[path.name] = SkillContent(path.name, path)

    def get_provider(self, provider_name: str) -> AgentProvider:
        """Get or create a provider instance (lazy init)."""
        if provider_name not in self._providers:
            cls = _PROVIDER_MAP.get(provider_name)
            if cls is None:
                raise ValueError(f"Unknown provider: {provider_name}")
            self._providers[provider_name] = cls()
        return self._providers[provider_name]

    def _emit(self, event: RoleEvent) -> None:
        """Emit a role event to the callback if registered."""
        if self._event_callback:
            self._event_callback(event)

    def get_role(self, name: str) -> RoleConfig:
        """Get a role config by name."""
        if name not in self._roles:
            raise KeyError(f"Role not found: {name}")
        return self._roles[name]

    def list_roles(self) -> list[str]:
        """List all registered role names."""
        return sorted(self._roles.keys())

    def execute_role(self, name: str, context: dict | None = None) -> AgentResult:
        """Execute a role: compose skill prompts → call provider → return result.

        Args:
            name: Role name (must match a YAML config).
            context: Additional context passed to the provider.
                     'task' key is the main user prompt.

        Returns:
            AgentResult from the provider.
        """
        role = self.get_role(name)
        provider = self.get_provider(role.provider)

        # Compose system prompt from all skills
        skill_prompts = []
        for skill_name in role.skills:
            skill = self._skills.get(skill_name)
            if skill and skill.prompt:
                skill_prompts.append(skill.prompt)

        system_prompt = "\n\n".join(skill_prompts) if skill_prompts else None

        ctx = dict(context or {})
        task = ctx.pop("task", "")

        now = datetime.now(tz=timezone.utc)
        self._emit(RoleEvent(
            role_name=name,
            event_type="started",
            message=f"Executing role '{name}' with provider '{role.provider}'",
            timestamp=now,
        ))

        try:
            provider_context = {"system": system_prompt} if system_prompt else None
            result = provider.execute(task, context=provider_context)

            self._emit(RoleEvent(
                role_name=name,
                event_type="completed",
                message=f"Role '{name}' completed in {result.duration_seconds:.1f}s",
                timestamp=datetime.now(tz=timezone.utc),
            ))
            return result

        except Exception:
            self._emit(RoleEvent(
                role_name=name,
                event_type="failed",
                message=f"Role '{name}' failed",
                timestamp=datetime.now(tz=timezone.utc),
            ))
            raise
