import pandas as pd
import pytest

from src.engine.backtest import run_backtest

DATES = ["20240101", "20240102", "20240103", "20240104", "20240105"]
STOCKS = ["000001.SZ", "000002.SZ"]


def _make_daily_df():
    rows = []
    for d in DATES:
        for s in STOCKS:
            rows.append({"ts_code": s, "trade_date": d, "open": 10.0, "close": 10.0,
                         "high": 10.5, "low": 9.5, "pre_close": 10.0, "vol": 1000})
    return pd.DataFrame(rows)


def test_basic_backtest():
    daily_df = _make_daily_df()
    signals = pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5})
    rankings = {d: STOCKS for d in DATES}

    result = run_backtest(daily_df, signals, rankings, initial_capital=100000)

    assert "nav" in result
    assert "trades" in result
    assert "daily_log" in result
    assert len(result["nav"]) == 5
    assert result["nav"].iloc[0] == pytest.approx(100000, rel=1e-2)


def test_zero_position():
    daily_df = _make_daily_df()
    signals = pd.DataFrame({"trade_date": DATES, "position": [0.0] * 5})
    rankings = {d: STOCKS for d in DATES}

    result = run_backtest(daily_df, signals, rankings, initial_capital=100000)

    assert all(v == pytest.approx(100000) for v in result["nav"])
    assert len(result["trades"]) == 0


def test_trade_calendar_can_extend_beyond_signal_dates():
    daily_df = _make_daily_df()
    signals = pd.DataFrame({"trade_date": DATES[:3], "position": [1.0, 1.0, 1.0]})
    rankings = {d: STOCKS for d in DATES}

    result = run_backtest(daily_df, signals, rankings, initial_capital=100000, trade_dates=DATES)

    assert list(result["nav"].index) == DATES
    assert len(result["daily_turnover"]) == len(DATES)


def test_trade_pnls_use_realized_round_trip_pnl():
    daily_df = _make_daily_df()
    signals = pd.DataFrame({"trade_date": DATES[:2], "position": [1.0, 0.0]})
    rankings = {d: [STOCKS[0]] for d in DATES}

    result = run_backtest(daily_df, signals, rankings, initial_capital=100000, trade_dates=DATES[:2])

    assert len(result["trade_pnls"]) == 1
    assert result["trade_pnls"].iloc[0] < 0
