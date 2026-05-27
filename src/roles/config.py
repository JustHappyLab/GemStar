"""RoleConfig — Pydantic schema for role YAML configuration.

CALLING SPEC:
    RoleConfig loaded from YAML via RoleRegistry.

SIDE EFFECTS:
    None — pure schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["api", "claude_code", "gemini_cli", "codex_cli"]


class RoleConfig(BaseModel):
    """Configuration for a single role loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    provider: ProviderName = "api"
    model: str | None = None
    skills: list[str] = Field(default_factory=list)
    timeout: int = Field(default=120, gt=0, le=3600)
