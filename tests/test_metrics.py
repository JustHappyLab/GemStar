import numpy as np
import pandas as pd
from src.engine.metrics import calc_cagr, calc_sharpe, calc_max_drawdown, calc_win_rate, calc_profit_factor


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
