"""Generate stock rankings from cross-sectional factor scores.

CALLING SPEC:
    rankings = build_rankings(
        daily_df=pd.DataFrame,
        index_daily=pd.DataFrame,
        fina_df=pd.DataFrame,
        factors=list[FactorWeightV1],
        top_n=int,
        trade_dates=list[str],
    ) -> dict[str, list[str]]
        Returns {trade_date: [stock_code, ...]} mapping.
"""

from __future__ import annotations

import pandas as pd

from src.ranker.factors import compute_all_factors
from src.ranker.normalize import winsorize_mad, zscore_cross_section
from src.ranker.scorer import compute_composite_score, rank_top_n
from src.orchestrator.universe import UniverseResolution, filter_group_for_universe, resolve_universe_value
from src.schemas.strategy import FactorWeightV1


def build_rankings(
    daily_df: pd.DataFrame,
    index_daily: pd.DataFrame,
    fina_df: pd.DataFrame,
    factors: list[FactorWeightV1],
    top_n: int,
    trade_dates: list[str],
    *,
    universe: str | UniverseResolution = "auto",
    stock_basic: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Compute per-date stock rankings from factor scores.

    Parameters
    ----------
    daily_df : DataFrame
        Daily OHLCV + basic data (ts_code, trade_date, close, pe_ttm, pb, turnover_rate, ...).
    index_daily : DataFrame
        Index daily data (trade_date, close).
    fina_df : DataFrame
        Financial indicator data (ts_code, ann_date, end_date, roe, revenue_yoy, netprofit_yoy).
    factors : list[FactorWeightV1]
        Factor weights from strategy config.
    top_n : int
        Number of top stocks to select per date.
    trade_dates : list[str]
        Trading dates to rank for (YYYYMMDD).
    universe : str | UniverseResolution
        Strategy universe preset or resolved universe.
    stock_basic : DataFrame, optional
        Stock metadata with list_date / delist_date used for point-in-time
        active-universe filtering.

    Returns
    -------
    dict mapping each trade_date to a list of stock codes.
    """
    if not trade_dates:
        return {}

    weights = {f.factor_id: f.weight for f in factors}

    # Compute cross-sectional factors
    factor_df = compute_all_factors(daily_df, index_daily, fina_df)
    if factor_df.empty:
        return {}

    # Keep only the factor columns we need
    available = [c for c in weights if c in factor_df.columns]
    if not available:
        return {}

    # Filter to target dates
    factor_df = factor_df[factor_df["trade_date"].isin(trade_dates)].copy()
    if factor_df.empty:
        return {}

    # Per-date cross-sectional normalization and scoring
    resolution = resolve_universe_value(universe)
    rankings: dict[str, list[str]] = {}
    for date, group in factor_df.groupby("trade_date"):
        g = filter_group_for_universe(
            group,
            stock_basic=stock_basic,
            trade_date=str(date),
            resolution=resolution,
        )
        if g.empty:
            rankings[str(date)] = []
            continue

        for col in available:
            g[col] = winsorize_mad(g[col])
            g[col] = zscore_cross_section(g[col])

        scored = compute_composite_score(g, weights)
        top = rank_top_n(scored, top_n)
        rankings[str(date)] = top["ts_code"].tolist()

    return rankings
