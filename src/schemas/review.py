"""Reviewer notes schema — LLM-generated verdict explanation.

CALLING SPEC:
    ReviewNotesV1 is the output of the Reviewer LLM role. It explains
    why a strategy passed/failed RuleJudge gates and highlights risks.
    It has NO state change authority — that belongs to VerdictV1 alone.

SIDE EFFECTS:
    None.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewNotesV1(BaseModel):
    version: Literal["ReviewNotesV1"] = "ReviewNotesV1"
    strategy_id: str
    run_id: str = ""
    verdict_summary: str = ""
    explanation: str = ""
    risk_highlights: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
