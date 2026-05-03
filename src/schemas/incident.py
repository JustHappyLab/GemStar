"""Incident schema — pipeline failure classification artifact.

CALLING SPEC:
    IncidentV1 captures a classified pipeline failure. Produced by
    OpsClassifier, consumed by the incident FSM and reporter.

SIDE EFFECTS:
    None.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncidentV1(BaseModel):
    version: Literal["IncidentV1"] = "IncidentV1"
    incident_id: str
    run_id: str
    detected_at: datetime
    state: Literal[
        "detected",
        "classified",
        "retrying",
        "degraded",
        "manual_attention",
        "engineering_task_created",
        "resolved",
    ] = "detected"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    category: str = "unknown"
    error_message: str = ""
    traceback: str = ""
    context: dict[str, str] = Field(default_factory=dict)
    resolution_notes: str = ""
    resolved_at: datetime | None = None
