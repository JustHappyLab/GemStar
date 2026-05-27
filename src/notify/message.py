"""Canonical notification payloads.

CALLING SPEC:
    message = NotificationMessageV1(
        message_id=str,
        title=str,
        body=str,
        severity="info" | "warning" | "critical",
        decision_id=str | None,
        action=str | None,
        symbols=list[str],
    )

SIDE EFFECTS:
    None. This module only validates notification payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


NotificationSeverity = Literal["info", "warning", "critical"]


class NotificationMessageV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["NotificationMessageV1"] = "NotificationMessageV1"
    message_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)
    severity: NotificationSeverity = "info"
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    decision_id: str | None = None
    action: str | None = None
    symbols: list[str] = Field(default_factory=list)
