"""Engineering task schemas.

CALLING SPEC:
    EngineeringTaskV1 records a bounded code-change request created by the
    orchestrator.  It is an artifact, not an automatic approval to merge code.

SIDE EFFECTS:
    None.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EngineeringRole = Literal["engineer", "bugfix"]
EngineeringTaskState = Literal[
    "created",
    "running",
    "completed",
    "rejected",
    "failed",
]
EngineeringReason = Literal[
    "unsupported_capability",
    "code_bug",
    "manual_attention",
]
EngineeringExecutionStatus = Literal[
    "dry_run",
    "completed",
    "rejected",
    "failed",
]


class EngineeringTaskV1(BaseModel):
    version: Literal["EngineeringTaskV1"] = "EngineeringTaskV1"
    task_id: str
    run_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    state: EngineeringTaskState = "created"
    role: EngineeringRole
    reason: EngineeringReason
    source_step: str
    strategy_id: str = ""
    strategy_path: str = ""
    error_message: str = ""
    traceback: str = ""
    context: dict[str, str] = Field(default_factory=dict)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    auto_apply: bool = False
    max_attempts: int = 1
    instructions: str = ""


class EngineeringPathViolationV1(BaseModel):
    path: str
    reason: str
    pattern: str | None = None


class EngineeringExecutionV1(BaseModel):
    version: Literal["EngineeringExecutionV1"] = "EngineeringExecutionV1"
    task_id: str
    run_id: str
    role: EngineeringRole
    status: EngineeringExecutionStatus
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    provider: str = ""
    output: str = ""
    prompt: str = ""
    changed_paths: list[str] = Field(default_factory=list)
    preexisting_changed_paths: list[str] = Field(default_factory=list)
    violations: list[EngineeringPathViolationV1] = Field(default_factory=list)
    error_message: str = ""
