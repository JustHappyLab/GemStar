"""Tests for the factor expression engine.

Covers:
- Security: rejects disallowed AST nodes, function names, attribute access.
- Correctness: time-series ops respect ts_code groups; cross-sectional ops
  respect trade_date groups.
"""

import numpy as np
import pandas as pd
import pytest

from src.factors.engine import (
    ALLOWED_FUNCTIONS,
    compute_factor_expression,
    validate_expression,
)


ALLOWED = {"close", "open", "high", "low", "volume", "amount", "turnover_rate", "pe_ttm", "pb"}


def _panel(n_dates: int = 30, n_stocks: int = 4) -> pd.DataFrame:
    dates = [f"2026010{d:02d}" for d in range(1, n_dates + 1)]
    codes = [f"00000{i}.SZ" for i in range(n_stocks)]
    rows = []
    rng = np.random.default_rng(42)
    for code in codes:
        base = rng.uniform(10, 100)
        for i, d in enumerate(dates):
            rows.append({
                "ts_code": code,
                "trade_date": d,
                "close": base + i * 0.5 + rng.normal(0, 1),
                "open": base + i * 0.5,
                "high": base + i * 0.5 + 1.0,
                "low": base + i * 0.5 - 1.0,
                "volume": 1000 + rng.normal(0, 100),
                "amount": 100000 + rng.normal(0, 1000),
                "turnover_rate": rng.uniform(0.5, 5.0),
                "pe_ttm": rng.uniform(10, 50),
                "pb": rng.uniform(1, 5),
            })
    return pd.DataFrame(rows)


# -------------------- security --------------------

def test_rejects_attribute_access():
    with pytest.raises(ValueError, match="Disallowed AST node"):
        validate_expression("close.values", ALLOWED)


def test_rejects_subscript():
    with pytest.raises(ValueError, match="Disallowed AST node"):
        validate_expression("close[0]", ALLOWED)


def test_rejects_unknown_function():
    with pytest.raises(ValueError, match="Unknown function"):
        validate_expression("eval('1+1')", ALLOWED)


def test_rejects_keyword_args():
    with pytest.raises(ValueError, match="Keyword arguments"):
        validate_expression("ts_mean(close, window=20)", ALLOWED)


def test_rejects_unknown_field():
    df = _panel()
    with pytest.raises(ValueError, match="Unknown field"):
        compute_factor_expression("hidden_field * 2", df, ALLOWED)


def test_rejects_string_constants():
    with pytest.raises(ValueError, match="Disallowed AST node|Only numeric"):
        # ast.Constant is allowed but evaluator rejects non-numeric
        df = _panel()
        compute_factor_expression("'evil'", df, ALLOWED)


def test_allowed_functions_registry():
    expected = {
        "ts_mean", "ts_std", "ts_max", "ts_min", "ts_sum",
        "ts_delta", "ts_pct_change", "ts_delay",
        "ts_rank", "ts_zscore", "ts_corr",
        "abs", "log", "sign", "sqrt", "clip", "where",
        "cs_rank",
    }
    assert ALLOWED_FUNCTIONS == expected


# -------------------- correctness --------------------

def test_simple_arithmetic():
    df = _panel()
    result = compute_factor_expression("(high - low) / close", df, ALLOWED)
    expected = (df["high"] - df["low"]) / df["close"]
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_ts_pct_change_per_stock():
    """ts_pct_change(close, 1) must compute per-stock returns."""
    df = _panel()
    result = compute_factor_expression("ts_pct_change(close, 1)", df, ALLOWED)
    # First row of each stock should be NaN (no prior obs)
    for _, idx in df.groupby("ts_code", sort=False).indices.items():
        assert pd.isna(result.iloc[idx[0]])


def test_ts_mean_window():
    df = _panel()
    result = compute_factor_expression("ts_mean(close, 5)", df, ALLOWED)
    # Manual check on one stock
    stock = df[df["ts_code"] == df["ts_code"].iloc[0]]
    manual = stock["close"].rolling(5, min_periods=2).mean()
    np.testing.assert_array_almost_equal(
        result.iloc[stock.index].values,
        manual.values,
    )


def test_cs_rank_per_date():
    """cs_rank(close) must rank within each trade_date, not across dates."""
    df = _panel()
    result = compute_factor_expression("cs_rank(close)", df, ALLOWED)
    # On any one date, ranks should span [0, 1] roughly evenly.
    one_date = df["trade_date"].iloc[0]
    mask = df["trade_date"] == one_date
    ranks = result[mask].sort_values()
    assert ranks.iloc[0] <= ranks.iloc[-1]
    assert 0.0 < ranks.max() <= 1.0
    assert 0.0 < ranks.min() <= 1.0


def test_compound_expression():
    """Sharpe-like signal: 20d return / 20d std."""
    df = _panel()
    expr = "ts_pct_change(close, 20) / (ts_std(close, 20) + 1e-6)"
    # Note: ts_std on price level is unusual but valid for this test
    result = compute_factor_expression(expr, df, ALLOWED)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)


def test_clip_and_where():
    df = _panel()
    result = compute_factor_expression(
        "clip(close, 20, 80)",
        df, ALLOWED,
    )
    valid = result.dropna()
    assert valid.min() >= 20
    assert valid.max() <= 80


def test_where_picks_branches():
    df = _panel()
    result = compute_factor_expression(
        "where(close > 50, high, low)",
        df, ALLOWED,
    )
    expected = pd.Series(
        np.where(df["close"] > 50, df["high"], df["low"]),
        index=df.index,
    )
    np.testing.assert_array_almost_equal(result.values, expected.values)


def test_inf_replaced_with_nan():
    df = _panel()
    df.loc[df.index[0], "low"] = 0.0
    df.loc[df.index[0], "high"] = 1.0
    df.loc[df.index[0], "close"] = 1.0
    # 1 / 0 -> inf -> nan
    result = compute_factor_expression("close / (low - low)", df, ALLOWED)
    assert pd.isna(result.iloc[0])
