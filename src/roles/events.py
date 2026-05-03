"""RoleEvent — observable events emitted during role execution.

CALLING SPEC:
    RoleEvent dataclass — consumed by pipeline event collectors.

SIDE EFFECTS:
    None — pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass
class RoleEvent:
    """Event emitted during role execution for user visibility."""

    role_name: str
    event_type: Literal["started", "progress", "completed", "failed"]
    message: str
    timestamp: datetime
    artifact: Path | None = None
