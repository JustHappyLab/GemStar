"""RoleConfig — Pydantic schema for role YAML configuration.

CALLING SPEC:
    RoleConfig loaded from YAML via RoleRegistry.

SIDE EFFECTS:
    None — pure schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoleConfig(BaseModel):
    """Configuration for a single role loaded from YAML."""

    name: str
    description: str = ""
    provider: str = "api"
    skills: list[str] = Field(default_factory=list)
    approval: bool = False
    timeout: int = 120
