"""Orchestrator manifest schemas for run tracking and artifact management.

CALLING SPEC:
    Used by orchestrator/artifact_store.py and orchestrator/run_manifest.py.
    All models are Pydantic v2, JSON-serializable, with timezone-aware timestamps.

SIDE EFFECTS:
    None.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ArtifactEntry(BaseModel):
    uri: str
    sha256: str


class ArtifactManifestV1(BaseModel):
    version: Literal["ArtifactManifestV1"] = "ArtifactManifestV1"
    run_id: str
    step_id: str
    created_at: datetime
    inputs: list[ArtifactEntry] = Field(default_factory=list)
    outputs: list[ArtifactEntry] = Field(default_factory=list)
    status: Literal["success", "failed", "partial"] = "success"
    warnings: list[str] = Field(default_factory=list)
    latency_sec: float = 0.0


class RunManifestV1(BaseModel):
    version: Literal["RunManifestV1"] = "RunManifestV1"
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "completed", "failed", "degraded", "manual_attention"] = "running"
    step_statuses: dict[str, str] = Field(default_factory=dict)


class TaskEnvelopePolicy(BaseModel):
    allow_tools: bool = False
    allow_code_write: bool = False
    allow_network: bool = False


class TaskEnvelopeBudget(BaseModel):
    max_tokens: int = 3000
    max_seconds: int = 60
    max_retries: int = 2


class TaskEnvelopeV1(BaseModel):
    version: Literal["TaskEnvelopeV1"] = "TaskEnvelopeV1"
    run_id: str
    task_id: str
    role: str
    state_context: dict[str, str | None] = Field(default_factory=dict)
    input_artifacts: list[ArtifactEntry] = Field(default_factory=list)
    output_contract: str = ""
    budget: TaskEnvelopeBudget = Field(default_factory=TaskEnvelopeBudget)
    policy: TaskEnvelopePolicy = Field(default_factory=TaskEnvelopePolicy)
