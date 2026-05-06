"""Backtest metrics and IC report schemas.

CALLING SPEC:
    BacktestResultV1 is the canonical backtest output artifact.
    ICReportV1 wraps factor IC summary.
    SegmentMetricV1 models per-period performance.

SIDE EFFECTS:
    None.
"""

from typing import Literal

from pydantic import BaseModel, Field


class SegmentMetricV1(BaseModel):
    segment: str
    days: int = 0
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    alpha: float = 0.0


class MetricsV1(BaseModel):
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    peak_idx: str = ""
    trough_idx: str = ""
    calmar: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    completed_trades: int = 0
    annual_turnover_ratio: float = 0.0
    alpha: float = 0.0
    longest_drawdown_days: int = 0


class ICReportEntry(BaseModel):
    factor: str
    IC_mean: float | None = None
    IC_std: float | None = None
    IC_IR: float | None = None
    IC_positive_rate: float | None = None


class ICReportV1(BaseModel):
    version: Literal["ICReportV1"] = "ICReportV1"
    factors: list[ICReportEntry] = Field(default_factory=list)

class BacktestResultV1(BaseModel):
    version: Literal["BacktestResultV1"] = "BacktestResultV1"
    strategy_name: str
    run_id: str = ""
    backtest_period: str = ""
    capital: float = 0.0
    metrics: MetricsV1 = Field(default_factory=MetricsV1)
    segments: list[SegmentMetricV1] = Field(default_factory=list)
    ic_report: ICReportV1 | None = None
