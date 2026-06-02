"""Research ticket schema — output of deterministic research generation.

CALLING SPEC:
    ResearchTicketV1 is a single research hypothesis produced by the
    research analyst module, proposing a new factor, strategy, or weight change.

SIDE EFFECTS:
    None.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ResearchTicketV1(BaseModel):
    version: Literal["ResearchTicketV1"] = "ResearchTicketV1"
    ticket_id: str
    created_date: date
    ticket_type: Literal[
        "new_factor", "factor_tweak", "new_strategy", "weight_rebalance"
    ]
    hypothesis: str
    rationale: str
    affected_factors: list[str] = Field(default_factory=list)
    affected_sectors: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_regime: str | None = None
    source_events: list[str] = Field(default_factory=list)
    status: Literal["draft", "validated", "approved", "rejected"] = "draft"
