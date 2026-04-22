"""Performance metrics for the backtest engine.

CALLING SPEC:
    metrics = compute_all_metrics(
        nav=pd.Series,
        trade_pnls=pd.Series,
        daily_turnover=pd.Series,
        benchmark_nav=pd.Series,
        initial_capital=float,
        rf_annual=float,
    ) -> dict[str, float | int | str]
        Returns portfolio-level performance metrics using realized trade PnL
        and capital-normalized turnover.

SIDE EFFECTS:
    None.
"""

import numpy as np
import pandas as pd


def calc_cagr(nav: pd.Series, trading_days_per_year: int = 243) -> float:
    years = len(nav) / trading_days_per_year
    return (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1


def calc_sharpe(daily_returns: pd.Series, rf_annual: float = 0.025, trading_days_per_year: int = 243) -> float:
    if daily_returns.empty:
        return float("nan")
    rf_daily = rf_annual / trading_days_per_year
    excess = daily_returns - rf_daily
    volatility = excess.std()
    if pd.isna(volatility) or volatility == 0:
        return 0.0
    return excess.mean() / volatility * np.sqrt(trading_days_per_year)


def calc_max_drawdown(nav: pd.Series) -> tuple[float, object, object]:
    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    trough_idx = drawdown.idxmin()
    peak_idx = nav.loc[:trough_idx].idxmax()
    return -drawdown.min(), peak_idx, trough_idx


def calc_calmar(cagr: float, max_dd: float) -> float:
    return cagr / max_dd if max_dd != 0 else float('inf')


def calc_win_rate(trade_pnls: pd.Series) -> float:
    if trade_pnls.empty:
        return float("nan")
    return (trade_pnls > 0).sum() / len(trade_pnls)


def calc_profit_factor(trade_pnls: pd.Series) -> float:
    if trade_pnls.empty:
        return float("nan")
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def calc_turnover_ratio_series(nav: pd.Series, daily_turnover: pd.Series, initial_capital: float) -> pd.Series:
    prior_nav = nav.shift(1).fillna(float(initial_capital))
    denominator = prior_nav.replace(0.0, np.nan)
    return (daily_turnover.astype(float) / denominator).fillna(0.0)


def calc_annual_turnover(turnover_ratio: pd.Series, trading_days_per_year: int = 243) -> float:
    if turnover_ratio.empty:
        return float("nan")
    return turnover_ratio.mean() * trading_days_per_year


def compute_all_metrics(
    nav: pd.Series,
    trade_pnls: pd.Series,
    daily_turnover: pd.Series,
    benchmark_nav: pd.Series,
    initial_capital: float,
    rf_annual: float = 0.025,
) -> dict:
    daily_returns = nav.pct_change().dropna()
    turnover_ratio = calc_turnover_ratio_series(nav, daily_turnover, initial_capital)
    cagr = calc_cagr(nav)
    mdd, peak_idx, trough_idx = calc_max_drawdown(nav)
    bench_cagr = calc_cagr(benchmark_nav)
    alpha = cagr - bench_cagr

    cummax = nav.cummax()
    in_dd = nav < cummax
    groups = (~in_dd).cumsum()
    longest_dd_days = in_dd.groupby(groups).sum().max() if in_dd.any() else 0

    return {
        'cagr': cagr,
        'sharpe': calc_sharpe(daily_returns, rf_annual),
        'max_drawdown': mdd,
        'peak_idx': peak_idx,
        'trough_idx': trough_idx,
        'calmar': calc_calmar(cagr, mdd),
        'win_rate': calc_win_rate(trade_pnls),
        'profit_factor': calc_profit_factor(trade_pnls),
        'completed_trades': int(len(trade_pnls)),
        'annual_turnover_ratio': calc_annual_turnover(turnover_ratio),
        'alpha': alpha,
        'longest_drawdown_days': int(longest_dd_days),
    }


def auto_segments(start: str, end: str) -> list[tuple[str, str]]:
    """Split a date range into ~1-year segments."""
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    segs = []
    while cur < end_ts:
        seg_end = min(cur + pd.DateOffset(years=1) - pd.Timedelta(days=1), end_ts)
        segs.append((cur.strftime("%Y%m%d"), seg_end.strftime("%Y%m%d")))
        cur = cur + pd.DateOffset(years=1)
    return segs


def compute_segment_metrics(
    nav: pd.Series,
    benchmark_nav: pd.Series,
    segments: list[tuple[str, str]],
    rf_annual: float = 0.025,
) -> list[dict]:
    """Compute key metrics for each (start, end) date segment."""
    results = []
    for seg_start, seg_end in segments:
        mask = (nav.index >= seg_start) & (nav.index <= seg_end)
        seg_nav = nav[mask]
        if len(seg_nav) < 2:
            continue
        seg_bench = benchmark_nav.reindex(seg_nav.index).ffill()
        daily_ret = seg_nav.pct_change().dropna()
        cagr = calc_cagr(seg_nav)
        mdd, _, _ = calc_max_drawdown(seg_nav)
        bench_cagr = calc_cagr(seg_bench) if len(seg_bench) >= 2 else 0.0
        results.append({
            "segment": f"{seg_start}~{seg_end}",
            "days": len(seg_nav),
            "cagr": cagr,
            "sharpe": calc_sharpe(daily_ret, rf_annual),
            "max_drawdown": mdd,
            "alpha": cagr - bench_cagr,
        })
    return results
