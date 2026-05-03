"""Tests for src/ranker/ic.py."""

import numpy as np
import pandas as pd

from src.ranker.ic import compute_daily_rank_ic, summarize_ic


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_daily(ts_codes, dates, close_values):
    """Build a minimal daily_df with ts_code, trade_date, close."""
    return pd.DataFrame({
        "ts_code": ts_codes,
        "trade_date": dates,
        "close": close_values,
    })


def _make_factors(ts_codes, dates, factor_dict):
    """Build a minimal factors_df.  factor_dict maps col_name -> values."""
    df = pd.DataFrame({"ts_code": ts_codes, "trade_date": dates})
    for col, vals in factor_dict.items():
        df[col] = vals
    return df


# ---------------------------------------------------------------------------
# 1. Known IC: perfect positive monotonic relationship => IC ~ 1.0
# ---------------------------------------------------------------------------

def test_rank_ic_known_positive():
    """When factor is perfectly rank-ordered with fwd return, IC should be ~1."""
    n = 20
    dates = ["20240101"] * n
    codes = [f"S{i:03d}" for i in range(n)]

    # close prices that produce strictly increasing forward returns
    # pct_change().shift(-1) means close[i+1]/close[i] - 1 for each ts_code.
    # With a single date group, shift(-1) yields NaN for all rows (no next date
    # for the same ts_code).  So we need >= 2 dates per ts_code.
    dates_a = ["20240101"] * n
    dates_b = ["20240102"] * n
    codes_full = codes + codes

    # close on day1: 100, 101, 102, ...  close on day2: shifted up so fwd_ret
    # is monotonically increasing and matches factor order.
    close_a = [100 + i for i in range(n)]
    # fwd_ret_i = close_b[i] / close_a[i] - 1.  Make close_b proportional to
    # factor so rank correlation is perfect.
    factor_vals = list(range(n))  # 0, 1, 2, ...
    close_b = [close_a[i] * (1 + factor_vals[i] * 0.01) for i in range(n)]

    daily_df = _make_daily(codes_full, dates_a + dates_b, close_a + close_b)
    factors_df = _make_factors(codes, dates_a, {"f1": factor_vals})

    ic_df = compute_daily_rank_ic(factors_df, daily_df, ["f1"])

    # Only date "20240101" survives (it has the forward return to 20240102).
    assert len(ic_df) == 1
    assert ic_df.loc[0, "trade_date"] == "20240101"
    assert abs(ic_df.loc[0, "f1"] - 1.0) < 1e-10, (
        f"Expected IC ~ 1.0, got {ic_df.loc[0, 'f1']}"
    )


# ---------------------------------------------------------------------------
# 2. Single factor — verify output shape
# ---------------------------------------------------------------------------

def test_rank_ic_single_factor_shape():
    n = 10
    dates_a = ["20240101"] * n
    dates_b = ["20240102"] * n
    codes = [f"S{i:03d}" for i in range(n)]
    close_a = [100.0 + i for i in range(n)]
    close_b = [101.0 + i for i in range(n)]

    daily_df = _make_daily(codes + codes, dates_a + dates_b, close_a + close_b)
    factors_df = _make_factors(codes, dates_a, {"alpha": np.arange(n, dtype=float)})

    ic_df = compute_daily_rank_ic(factors_df, daily_df, ["alpha"])

    assert list(ic_df.columns) == ["trade_date", "alpha"]
    assert len(ic_df) == 1  # one date group
    assert ic_df["alpha"].dtype == float or ic_df["alpha"].dtype == np.float64


# ---------------------------------------------------------------------------
# 3. Multiple factors — all present in output
# ---------------------------------------------------------------------------

def test_rank_ic_multiple_factors():
    n = 10
    dates_a = ["20240101"] * n
    dates_b = ["20240102"] * n
    codes = [f"S{i:03d}" for i in range(n)]
    close_a = [100.0 + i for i in range(n)]
    close_b = [101.0 + i for i in range(n)]

    daily_df = _make_daily(codes + codes, dates_a + dates_b, close_a + close_b)
    factors_df = _make_factors(
        codes, dates_a, {"f1": np.arange(n), "f2": np.arange(n)[::-1], "f3": np.ones(n)}
    )

    ic_df = compute_daily_rank_ic(factors_df, daily_df, ["f1", "f2", "f3"])

    for col in ["trade_date", "f1", "f2", "f3"]:
        assert col in ic_df.columns, f"{col} missing from output"


# ---------------------------------------------------------------------------
# 4. summarize_ic correctness
# ---------------------------------------------------------------------------

def test_summarize_ic_values():
    """Hand-compute mean, std, IR, positive_rate for a known IC series."""
    ic_df = pd.DataFrame({
        "trade_date": ["20240101", "20240102", "20240103", "20240104"],
        "f1": [0.10, 0.20, 0.30, -0.05],
    })

    summary = summarize_ic(ic_df)

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["factor"] == "f1"

    s = ic_df["f1"]
    assert abs(row["IC_mean"] - s.mean()) < 1e-12
    assert abs(row["IC_std"] - s.std()) < 1e-12
    expected_ir = s.mean() / s.std()
    assert abs(row["IC_IR"] - expected_ir) < 1e-12
    expected_pos = (s > 0).mean()
    assert abs(row["IC_positive_rate"] - expected_pos) < 1e-12


# ---------------------------------------------------------------------------
# 5. summarize_ic with empty DataFrame — graceful handling
# ---------------------------------------------------------------------------

def test_summarize_ic_empty():
    ic_df = pd.DataFrame(columns=["trade_date", "f1"])
    summary = summarize_ic(ic_df)

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["factor"] == "f1"
    assert row["IC_mean"] is None
    assert row["IC_std"] is None
    assert row["IC_IR"] is None
    assert row["IC_positive_rate"] is None


# ---------------------------------------------------------------------------
# 6. Missing data — NaN fill, groups with < 5 valid rows skipped
# ---------------------------------------------------------------------------

def test_rank_ic_missing_data():
    """Groups with too few valid observations should produce NaN IC, not crash."""
    n = 10
    dates_a = ["20240101"] * n
    dates_b = ["20240102"] * n
    codes = [f"S{i:03d}" for i in range(n)]
    close_a = [100.0 + i for i in range(n)]
    close_b = [101.0 + i for i in range(n)]

    # Inject NaNs into factor so that dropna leaves < 5 rows
    factor_vals = [np.nan] * 8 + [1.0, 2.0]  # only 2 valid

    daily_df = _make_daily(codes + codes, dates_a + dates_b, close_a + close_b)
    factors_df = _make_factors(codes, dates_a, {"f1": factor_vals})

    ic_df = compute_daily_rank_ic(factors_df, daily_df, ["f1"])

    # Date group has >= 5 total rows (10), so it survives the outer filter.
    # But only 2 valid (non-NaN) factor rows => inner check triggers None.
    assert len(ic_df) == 1
    assert ic_df.loc[0, "f1"] is None
