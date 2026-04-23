"""Backtest engine sanity check with hand-calculable scenarios.

Each test uses synthetic data where the expected NAV can be computed
by hand, then asserts the engine produces the same result.

Run:  uv run python -m pytest tests/test_engine_sanity.py -v
"""

import pandas as pd
import pytest

from src.engine.backtest import run_backtest
from src.portfolio.cost import COMMISSION_RATE, MIN_COMMISSION, STAMP_TAX_HALF, SLIPPAGE_RATE


def _daily(rows):
    """Build daily_df from (code, date, open, close, pre_close, vol) tuples."""
    records = []
    for code, date, opn, cls, pre_cls, vol in rows:
        records.append({
            "ts_code": code, "trade_date": date,
            "open": opn, "close": cls, "high": cls, "low": opn,
            "pre_close": pre_cls, "vol": vol,
        })
    return pd.DataFrame(records)


def _signals(dates, positions):
    return pd.DataFrame({"trade_date": dates, "position": positions})


def _cost(price, shares, direction):
    """Mirror current cost model (slippage included in cost)."""
    turnover = price * shares
    commission = max(turnover * COMMISSION_RATE, MIN_COMMISSION)
    slippage = turnover * SLIPPAGE_RATE
    stamp = 0.0
    if direction == "sell":
        stamp = turnover * STAMP_TAX_HALF
    return commission + stamp + slippage


# ---------------------------------------------------------------------------
# Scenario 1: buy-and-hold, NAV should track close price
# ---------------------------------------------------------------------------

def test_buy_and_hold_nav_increases():
    daily = _daily([
        ("A", "20240101", 10.0, 11.0, 10.0, 1_000_000),
        ("A", "20240102", 11.0, 12.0, 11.0, 1_000_000),
        ("A", "20240103", 12.0, 13.0, 12.0, 1_000_000),
    ])
    signals = _signals(["20240101", "20240102", "20240103"], [1.0, 1.0, 1.0])
    rankings = {d: ["A"] for d in ["20240101", "20240102", "20240103"]}

    result = run_backtest(daily, signals, rankings, initial_capital=100_000,
                          trade_dates=["20240101", "20240102", "20240103"])

    nav = result["nav"]
    assert len(nav) == 3
    assert nav.iloc[0] > 100_000   # close=11 > open=10
    assert nav.iloc[1] > nav.iloc[0]
    assert nav.iloc[2] > nav.iloc[1]


# ---------------------------------------------------------------------------
# Scenario 2: zero position = pure cash
# ---------------------------------------------------------------------------

def test_zero_position_exact_cash():
    daily = _daily([
        ("A", "20240101", 10.0, 15.0, 10.0, 1_000_000),
        ("A", "20240102", 15.0, 5.0,  15.0, 1_000_000),
    ])
    signals = _signals(["20240101", "20240102"], [0.0, 0.0])
    rankings = {d: ["A"] for d in ["20240101", "20240102"]}

    result = run_backtest(daily, signals, rankings, initial_capital=100_000,
                          trade_dates=["20240101", "20240102"])

    for v in result["nav"]:
        assert v == pytest.approx(100_000)
    assert len(result["trades"]) == 0


# ---------------------------------------------------------------------------
# Scenario 3: single round-trip, exact hand calculation
# ---------------------------------------------------------------------------

def test_single_round_trip_exact():
    """
    Day 1: buy 100 shares of A at open=100, close=105
    Day 2: sell all at open=110 (position → 0), close=110
    """
    daily = _daily([
        ("A", "20240101", 100.0, 105.0, 100.0, 1_000_000),
        ("A", "20240102", 110.0, 110.0, 105.0, 1_000_000),
    ])
    signals = _signals(["20240101", "20240102"], [1.0, 0.0])
    rankings = {"20240101": ["A"], "20240102": ["A"]}

    capital = 20_000.0
    result = run_backtest(daily, signals, rankings, initial_capital=capital,
                          trade_dates=["20240101", "20240102"])

    # --- Day 1: BUY ---
    buy_price = 100.0
    # target = 20000 * 1.0 / 1 / 100 = 200 → round to 200 shares
    # But need to fit to cash: 200 shares * 100 + cost
    buy_cost_200 = _cost(100.0, 200, "buy")
    needed_200 = 100.0 * 200 + buy_cost_200
    if needed_200 <= capital:
        shares = 200
        buy_cost = buy_cost_200
    else:
        shares = 100
        buy_cost = _cost(100.0, 100, "buy")

    cash_after_buy = capital - buy_price * shares - buy_cost
    nav_day1 = cash_after_buy + 105.0 * shares

    assert result["nav"].iloc[0] == pytest.approx(nav_day1, rel=1e-6)

    # --- Day 2: SELL ---
    sell_price = 110.0
    sell_cost = _cost(110.0, shares, "sell")
    cash_after_sell = cash_after_buy + sell_price * shares - sell_cost
    nav_day2 = cash_after_sell  # no holdings

    assert result["nav"].iloc[1] == pytest.approx(nav_day2, rel=1e-6)
    assert len(result["trades"]) == 2


# ---------------------------------------------------------------------------
# Scenario 4: limit-up stock should not be bought
# ---------------------------------------------------------------------------

def test_limit_up_blocks_buy():
    """Open is 20% above pre_close → limit up → engine should skip buy."""
    daily = _daily([
        ("B", "20240101", 12.0, 12.0, 10.0, 1_000_000),  # +20% → limit up
    ])
    signals = _signals(["20240101"], [1.0])
    rankings = {"20240101": ["B"]}

    result = run_backtest(daily, signals, rankings, initial_capital=100_000,
                          trade_dates=["20240101"])

    assert len(result["trades"]) == 0
    assert result["nav"].iloc[0] == pytest.approx(100_000)


# ---------------------------------------------------------------------------
# Scenario 5: limit-down stock should not be sold
# ---------------------------------------------------------------------------

def test_limit_down_blocks_sell():
    """
    Day 1: buy stock A (normal)
    Day 2: A opens at limit-down (-20%), position → 0 but sell should be blocked
    """
    daily = _daily([
        ("A", "20240101", 10.0, 10.0, 10.0, 1_000_000),
        ("A", "20240102", 8.0,  8.0,  10.0, 1_000_000),  # -20% → limit down
    ])
    signals = _signals(["20240101", "20240102"], [1.0, 0.0])
    rankings = {"20240101": ["A"], "20240102": ["A"]}

    result = run_backtest(daily, signals, rankings, initial_capital=100_000,
                          trade_dates=["20240101", "20240102"])

    # Day 1: bought some shares
    buy_trades = [t for t in result["trades"] if t["dir"] == "buy"]
    assert len(buy_trades) == 1

    # Day 2: sell should be blocked (limit down)
    sell_trades = [t for t in result["trades"] if t["dir"] == "sell"]
    assert len(sell_trades) == 0

    # Still holding → NAV reflects close=8
    assert result["nav"].iloc[1] < result["nav"].iloc[0]


# ---------------------------------------------------------------------------
# Scenario 6: cost symmetry — buy then sell at same price should lose money
# ---------------------------------------------------------------------------

def test_round_trip_same_price_loses_money():
    """Buy and sell at the same open price → NAV < initial due to costs."""
    daily = _daily([
        ("A", "20240101", 50.0, 50.0, 50.0, 1_000_000),
        ("A", "20240102", 50.0, 50.0, 50.0, 1_000_000),
    ])
    signals = _signals(["20240101", "20240102"], [1.0, 0.0])
    rankings = {"20240101": ["A"], "20240102": ["A"]}

    result = run_backtest(daily, signals, rankings, initial_capital=100_000,
                          trade_dates=["20240101", "20240102"])

    # Must lose money due to commission + slippage + stamp tax
    assert result["nav"].iloc[1] < 100_000
