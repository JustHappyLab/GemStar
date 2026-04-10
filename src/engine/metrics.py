import numpy as np
import pandas as pd


def calc_cagr(nav: pd.Series, trading_days_per_year: int = 243) -> float:
    years = len(nav) / trading_days_per_year
    return (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1


def calc_sharpe(daily_returns: pd.Series, rf_annual: float = 0.025, trading_days_per_year: int = 243) -> float:
    rf_daily = rf_annual / trading_days_per_year
    excess = daily_returns - rf_daily
    return excess.mean() / excess.std() * np.sqrt(trading_days_per_year)


def calc_max_drawdown(nav: pd.Series) -> tuple[float, object, object]:
    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    trough_idx = drawdown.idxmin()
    peak_idx = nav.loc[:trough_idx].idxmax()
    return -drawdown.min(), peak_idx, trough_idx


def calc_calmar(cagr: float, max_dd: float) -> float:
    return cagr / max_dd if max_dd != 0 else float('inf')


def calc_win_rate(trade_pnls: pd.Series) -> float:
    return (trade_pnls > 0).sum() / len(trade_pnls)


def calc_profit_factor(trade_pnls: pd.Series) -> float:
    gains = trade_pnls[trade_pnls > 0].sum()
    losses = -trade_pnls[trade_pnls < 0].sum()
    return gains / losses if losses != 0 else float('inf')


def calc_annual_turnover(daily_turnover: pd.Series, trading_days_per_year: int = 243) -> float:
    return daily_turnover.mean() * trading_days_per_year


def compute_all_metrics(nav: pd.Series, trade_pnls: pd.Series, daily_turnover: pd.Series,
                        benchmark_nav: pd.Series, rf_annual: float = 0.025) -> dict:
    daily_returns = nav.pct_change().dropna()
    bench_returns = benchmark_nav.pct_change().dropna()

    cagr = calc_cagr(nav)
    mdd, peak_idx, trough_idx = calc_max_drawdown(nav)
    bench_cagr = calc_cagr(benchmark_nav)
    alpha = cagr - bench_cagr

    # longest drawdown duration in days
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
        'annual_turnover': calc_annual_turnover(daily_turnover),
        'alpha': alpha,
        'longest_drawdown_days': int(longest_dd_days),
    }
