"""Strategy configuration schema.

CALLING SPEC:
    Validates strategy YAML via StrategyConfigV1.from_yaml(path) or
    StrategyConfigV1.model_validate(obj).
    FactorWeightV1 defines per-factor weighting; TimerConfigV1 selects
    timer mode; BacktestConfigV1 sets date range and capital.

SIDE EFFECTS:
    None.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class FactorWeightV1(BaseModel):
    factor_id: str
    weight: float = Field(ge=0.0, le=1.0)


class TimerConfigV1(BaseModel):
    mode: Literal["lstm", "ma", "full"] = "lstm"
    seq_len: int = 60
    horizon: int = 5
    retrain_months: int = 6
    epochs: int = 100
    batch_size: int = 64
    lr: float = 1e-3
    patience: int = 10


class BacktestConfigV1(BaseModel):
    start: str = "20220101"
    end: str = "20260501"
    capital: float = 200000.0
    rf_annual: float = 0.025
    volume_limit_pct: float = 0.25
    cost_multiplier: float = 1.0


class StrategyConfigV1(BaseModel):
    version: Literal["StrategyConfigV1"] = "StrategyConfigV1"
    name: str
    hypothesis: str = ""
    source_idea: str = ""
    universe: Literal["chinext", "all"] = "chinext"
    timer: TimerConfigV1 = Field(default_factory=TimerConfigV1)
    factors: list[FactorWeightV1] = Field(default_factory=list)
    top_n: int = Field(default=5, ge=1, le=50)
    rebalance: Literal["daily", "weekly", "monthly"] = "daily"
    backtest: BacktestConfigV1 = Field(default_factory=BacktestConfigV1)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "StrategyConfigV1":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
