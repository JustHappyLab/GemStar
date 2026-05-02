"""Daily report schema.

CALLING SPEC:
    DailyReportV1 is the structured report artifact produced by
    src/reporter/builder.py.  Fields are filled from verified
    downstream artifacts; content is Markdown rendered to IM.

SIDE EFFECTS:
    None.
"""

from datetime import date

from pydantic import BaseModel, Field


class ReportStrategyEntry(BaseModel):
    name: str
    rank: int = 0
    sharpe: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    alpha: float = 0.0
    rank_change: str = ""  # e.g. "new", "up", "down", "stable"


class DailyReportV1(BaseModel):
    version: str = "DailyReportV1"
    report_date: date
    run_id: str = ""
    market_summary: str = ""
    leaderboard: list[ReportStrategyEntry] = Field(default_factory=list)
    holdings_signal: list[str] = Field(default_factory=list)
    signals_summary: list[str] = Field(default_factory=list)
    factor_notes: list[str] = Field(default_factory=list)
    health_status: str = "ok"
    health_notes: list[str] = Field(default_factory=list)
    news_digest: list[str] = Field(default_factory=list)
