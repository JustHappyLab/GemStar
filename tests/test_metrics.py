import numpy as np
import pandas as pd
from src.engine.metrics import (
    calc_annual_turnover,
    calc_cagr,
    calc_max_drawdown,
    calc_profit_factor,
    calc_sharpe,
    calc_turnover_ratio_series,
    calc_win_rate,
    compute_all_metrics,
)


def test_cagr():
    nav = pd.Series(np.linspace(1, 2, 487))
    cagr = calc_cagr(nav)
    assert abs(cagr - 0.41) < 0.02


def test_sharpe_returns_float():
    returns = pd.Series(np.random.randn(100) * 0.01)
    assert isinstance(calc_sharpe(returns), float)


def test_max_drawdown():
    nav = pd.Series([1, 1.1, 1.2, 0.9, 1.0, 1.1])
    mdd, peak, trough = calc_max_drawdown(nav)
    assert abs(mdd - 0.25) < 1e-9


def test_win_rate():
    pnls = pd.Series([1, -1, 2, -0.5, 3])
    assert calc_win_rate(pnls) == 0.6


def test_profit_factor():
    pnls = pd.Series([1, -1, 2, -0.5, 3])
    assert calc_profit_factor(pnls) == 6.0 / 1.5


def test_turnover_ratio_series_is_capital_normalized():
    nav = pd.Series([100000.0, 110000.0, 121000.0])
    daily_turnover = pd.Series([10000.0, 22000.0, 12100.0])

    ratio = calc_turnover_ratio_series(nav, daily_turnover, initial_capital=100000.0)

    assert ratio.tolist() == [0.1, 0.22, 0.11]
    assert calc_annual_turnover(ratio, trading_days_per_year=10) == 1.4333333333333333


def test_compute_all_metrics_reports_completed_trades():
    nav = pd.Series([100000.0, 101000.0, 100500.0, 102000.0])
    benchmark_nav = pd.Series([100000.0, 100400.0, 100200.0, 100800.0])
    trade_pnls = pd.Series([100.0, -40.0, 60.0])
    daily_turnover = pd.Series([5000.0, 12000.0, 3000.0, 8000.0])

    metrics = compute_all_metrics(nav, trade_pnls, daily_turnover, benchmark_nav, initial_capital=100000.0)

    assert metrics["completed_trades"] == 3
    assert "annual_turnover_ratio" in metrics
