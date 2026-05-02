"""Scanner signal and market regime schemas.

CALLING SPEC:
    SignalEventV1 is a single notable event emitted by Scanner/EventScanner.
    MarketRegimeV1 captures the macro style/regime assessment from MacroAnalyst.

SIDE EFFECTS:
    None.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class SignalEventV1(BaseModel):
    version: Literal["SignalEventV1"] = "SignalEventV1"
    event_date: date
    event_id: str
    event_type: Literal[
        "policy_event",
        "earnings_surprise",
        "factor_drift",
        "sector_rotation",
        "northbound_flow",
        "sentiment_shift",
        "analyst_revision",
        "other",
    ] = "other"
    severity: Literal["low", "medium", "high"] = "low"
    summary: str = ""
    affected_sectors: list[str] = Field(default_factory=list)
    affected_symbols: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    recommended_next_action: str = ""


class MarketRegimeV1(BaseModel):
    version: Literal["MarketRegimeV1"] = "MarketRegimeV1"
    as_of_date: date
    regime: Literal["bullish", "bearish", "neutral", "volatile", "defensive"] = "neutral"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    key_drivers: list[str] = Field(default_factory=list)
    style_bias: str = ""  # e.g. "高股息", "成长", "小盘"
