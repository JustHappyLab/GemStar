"""Strategy verdict schema — RuleJudge output.

CALLING SPEC:
    VerdictV1 is the canonical state-recommendation artifact produced by
    src/judge/rules.py.  Orchestrator reads verdict.recommended_state and
    applies state transition policy.
    Each HardGateResultV1 documents one pass/fail gate.

SIDE EFFECTS:
    None.
"""

from typing import Literal

from pydantic import BaseModel, Field


class HardGateResultV1(BaseModel):
    name: str
    passed: bool
    value: float
    threshold: float
    note: str = ""


class VerdictV1(BaseModel):
    version: Literal["VerdictV1"] = "VerdictV1"
    strategy_id: str
    run_id: str = ""
    current_state: str = "backtested"
    recommended_state: Literal[
        "candidate", "paper", "active", "watchlist", "demoted", "retired", "rejected"
    ] = "rejected"
    hard_gates: list[HardGateResultV1] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
