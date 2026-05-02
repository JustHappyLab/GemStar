"""Strategy YAML adapter: load config, run backtest, package results.

CALLING SPEC:
    result = run_strategy_from_yaml(
        path=str | Path,
        daily_df=pd.DataFrame,
        signals=pd.DataFrame,
        rankings=dict[str, list[str]],
        benchmark_nav=pd.Series,
        ic_df=pd.DataFrame | None,
    ) -> BacktestResultV1

    Loads a strategy YAML, runs the backtest engine, computes metrics,
    segment breakdowns, and optional IC summary, returning a validated
    BacktestResultV1 artifact.

    Parameters:
        path:           Strategy YAML file path.
        daily_df:       OHLCV data (ts_code, trade_date, open, close, high, low,
                        pre_close, vol).
        signals:        Position signal DataFrame (trade_date, position).
        rankings:       trade_date -> ranked stock codes mapping.
        benchmark_nav:  Benchmark NAV series indexed by trade_date.
        ic_df:          Optional daily IC DataFrame for IC report generation.

SIDE EFFECTS:
    None.
"""

import math
from pathlib import Path

import pandas as pd

from src.engine.backtest import run_backtest
from src.engine.metrics import (
    auto_segments,
    compute_all_metrics,
    compute_segment_metrics,
)
from src.ranker.ic import summarize_ic
from src.schemas.metrics import (
    BacktestResultV1,
    ICReportEntry,
    ICReportV1,
    MetricsV1,
    SegmentMetricV1,
)
from src.schemas.strategy import StrategyConfigV1


def _clean_float(value: float) -> float:
    """Replace NaN / Inf with 0.0 for schema safety."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return 0.0
    return float(value)


def _build_metrics(raw: dict) -> MetricsV1:
    """Map compute_all_metrics dict to MetricsV1, sanitizing NaN/Inf."""
    return MetricsV1(
        cagr=_clean_float(raw["cagr"]),
        sharpe=_clean_float(raw["sharpe"]),
        max_drawdown=_clean_float(raw["max_drawdown"]),
        peak_idx=str(raw.get("peak_idx", "")),
        trough_idx=str(raw.get("trough_idx", "")),
        calmar=_clean_float(raw["calmar"]),
        win_rate=_clean_float(raw["win_rate"]),
        profit_factor=_clean_float(raw["profit_factor"]),
        completed_trades=int(raw.get("completed_trades", 0)),
        annual_turnover_ratio=_clean_float(raw["annual_turnover_ratio"]),
        alpha=_clean_float(raw["alpha"]),
        longest_drawdown_days=int(raw.get("longest_drawdown_days", 0)),
    )


def _build_segments(raw_list: list[dict]) -> list[SegmentMetricV1]:
    """Map compute_segment_metrics output to SegmentMetricV1 list."""
    return [
        SegmentMetricV1(
            segment=str(r["segment"]),
            days=int(r.get("days", 0)),
            cagr=_clean_float(r["cagr"]),
            sharpe=_clean_float(r["sharpe"]),
            max_drawdown=_clean_float(r["max_drawdown"]),
            alpha=_clean_float(r["alpha"]),
        )
        for r in raw_list
    ]


def _build_ic_report(ic_df: pd.DataFrame) -> ICReportV1:
    """Summarize IC DataFrame into ICReportV1."""
    summary = summarize_ic(ic_df)
    entries = []
    for _, row in summary.iterrows():
        entries.append(ICReportEntry(
            factor=str(row["factor"]),
            IC_mean=_clean_float(row["IC_mean"]) if row["IC_mean"] is not None else None,
            IC_std=_clean_float(row["IC_std"]) if row["IC_std"] is not None else None,
            IC_IR=_clean_float(row["IC_IR"]) if row["IC_IR"] is not None else None,
            IC_positive_rate=_clean_float(row["IC_positive_rate"]) if row["IC_positive_rate"] is not None else None,
        ))
    return ICReportV1(factors=entries)


def run_strategy_from_yaml(
    path: str | Path,
    daily_df: pd.DataFrame,
    signals: pd.DataFrame,
    rankings: dict[str, list[str]],
    benchmark_nav: pd.Series,
    ic_df: pd.DataFrame | None = None,
) -> BacktestResultV1:
    """Load strategy YAML, run backtest, and return BacktestResultV1."""
    config = StrategyConfigV1.from_yaml(path)
    bc = config.backtest

    bt = run_backtest(
        daily_df=daily_df,
        signals=signals,
        rankings=rankings,
        initial_capital=bc.capital,
        volume_limit_pct=bc.volume_limit_pct,
        cost_multiplier=bc.cost_multiplier,
    )

    raw_metrics = compute_all_metrics(
        nav=bt["nav"],
        trade_pnls=bt["trade_pnls"],
        daily_turnover=bt["daily_turnover"],
        benchmark_nav=benchmark_nav,
        initial_capital=bc.capital,
        rf_annual=bc.rf_annual,
    )

    segments = auto_segments(bc.start, bc.end)
    raw_segment_metrics = compute_segment_metrics(
        nav=bt["nav"],
        benchmark_nav=benchmark_nav,
        segments=segments,
        rf_annual=bc.rf_annual,
    )

    ic_report = _build_ic_report(ic_df) if ic_df is not None else None

    return BacktestResultV1(
        strategy_name=config.name,
        backtest_period=f"{bc.start}~{bc.end}",
        capital=bc.capital,
        metrics=_build_metrics(raw_metrics),
        segments=_build_segments(raw_segment_metrics),
        ic_report=ic_report,
    )
