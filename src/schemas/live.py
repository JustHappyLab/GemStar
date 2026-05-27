"""Live trading radar schemas.

CALLING SPEC:
    position = LivePositionV1(ts_code=str, shares=int, avg_cost=float)
    account = LiveAccountStateV1(cash=float, positions=list[LivePositionV1])
    snapshot = MarketSnapshotV1(ts_code=str, trade_date=str, last_price=float)
    target = TargetHoldingV1(ts_code=str, target_weight=float, target_shares=int)
    intent = TradingIntentV1(action=str, shares=int, reason=str)
    decision = LiveDecisionV1(
        decision_id=str,
        strategy_name=str,
        ts_code=str,
        intent=TradingIntentV1,
    )

SIDE EFFECTS:
    None. These models only validate and serialize live/paper trading data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TradeAction = Literal["buy", "sell", "reduce", "add", "hold", "blocked"]
DecisionSeverity = Literal["info", "warning", "critical"]
PaperTradeAction = Literal["buy", "sell", "reduce", "add"]


class LivePositionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["LivePositionV1"] = "LivePositionV1"
    ts_code: str = Field(min_length=6, max_length=16)
    shares: int = Field(ge=0, multiple_of=100)
    avg_cost: float = Field(ge=0.0)
    last_price: float | None = Field(default=None, gt=0.0)
    market_value: float = Field(default=0.0, ge=0.0)
    bought_today: bool = False


class LiveAccountStateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["LiveAccountStateV1"] = "LiveAccountStateV1"
    as_of: datetime = Field(default_factory=datetime.now)
    cash: float = Field(ge=0.0)
    total_value: float = Field(ge=0.0)
    positions: list[LivePositionV1] = Field(default_factory=list)


class MarketSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["MarketSnapshotV1"] = "MarketSnapshotV1"
    ts_code: str = Field(min_length=6, max_length=16)
    trade_date: str = Field(pattern=r"^\d{8}$")
    timestamp: datetime = Field(default_factory=datetime.now)
    last_price: float = Field(gt=0.0)
    open: float | None = Field(default=None, gt=0.0)
    high: float | None = Field(default=None, gt=0.0)
    low: float | None = Field(default=None, gt=0.0)
    pre_close: float | None = Field(default=None, gt=0.0)
    volume: float = Field(default=0.0, ge=0.0)
    limit_up: bool = False
    limit_down: bool = False
    source: str = "unknown"


class TargetHoldingV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["TargetHoldingV1"] = "TargetHoldingV1"
    ts_code: str = Field(min_length=6, max_length=16)
    target_weight: float = Field(ge=0.0, le=1.0)
    target_shares: int = Field(ge=0, multiple_of=100)
    reason: str = ""


class TradingIntentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["TradingIntentV1"] = "TradingIntentV1"
    action: TradeAction
    shares: int = Field(ge=0, multiple_of=100)
    reference_price: float | None = Field(default=None, gt=0.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str
    risk_flags: list[str] = Field(default_factory=list)


class LiveDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["LiveDecisionV1"] = "LiveDecisionV1"
    decision_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)
    strategy_name: str = Field(min_length=1)
    ts_code: str = Field(min_length=6, max_length=16)
    severity: DecisionSeverity = "info"
    intent: TradingIntentV1
    notify: bool = True


class PaperTradeRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["PaperTradeRecordV1"] = "PaperTradeRecordV1"
    execution_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)
    trade_date: str = Field(pattern=r"^\d{8}$")
    strategy_name: str = Field(min_length=1)
    ts_code: str = Field(min_length=6, max_length=16)
    action: PaperTradeAction
    shares: int = Field(gt=0, multiple_of=100)
    fill_price: float = Field(gt=0.0)
    confirmed: bool
    executed: bool
    position_after_shares: int = Field(ge=0, multiple_of=100)
