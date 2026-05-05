import pandas as pd
import numpy as np
import pytest
from src.data.cleaner import (
    apply_adjusted_prices,
    fill_missing_cross_section,
    filter_active_stocks,
    filter_new_stocks,
    filter_st,
    filter_suspended,
)


class TestFilterST:
    def test_removes_st_stocks(self):
        df = pd.DataFrame({"name": ["Normal", "ST Bad", "*ST Worse", "Good"], "ts_code": ["a", "b", "c", "d"]})
        result = filter_st(df)
        assert list(result["name"]) == ["Normal", "Good"]


class TestFilterNewStocks:
    def test_removes_recent_listings(self):
        df = pd.DataFrame({
            "ts_code": ["old", "new"],
            "name": ["A", "B"],
            "list_date": ["20230101", "20230320"],
            "delist_date": ["", ""],
        })
        result = filter_new_stocks(df, "20230401", min_days=60)
        assert list(result["ts_code"]) == ["old"]


class TestFilterActiveStocks:
    def test_filters_future_listings_and_past_delistings(self):
        df = pd.DataFrame(
            {
                "ts_code": ["active", "future", "gone"],
                "name": ["A", "B", "C"],
                "list_date": ["20220101", "20250101", "20200101"],
                "delist_date": ["", "", "20231231"],
            }
        )

        result = filter_active_stocks(df, "20240102")

        assert list(result["ts_code"]) == ["active"]


class TestFilterSuspended:
    def test_removes_zero_volume(self):
        df = pd.DataFrame({"ts_code": ["a", "b", "c"], "vol": [100, 0, 200]})
        result = filter_suspended(df)
        assert list(result["ts_code"]) == ["a", "c"]


class TestFillMissing:
    def test_fills_nan_with_median(self):
        df = pd.DataFrame({"x": [1.0, 2.0, np.nan, 4.0], "y": [10.0, np.nan, 30.0, 40.0]})
        result = fill_missing_cross_section(df, ["x", "y"])
        assert result["x"].iloc[2] == 2.0  # median of 1,2,4
        assert result["y"].iloc[1] == 30.0  # median of 10,30,40
        assert not result[["x", "y"]].isna().any().any()


class TestAdjustedPrices:
    def test_preserves_continuity_and_volume(self):
        daily = pd.DataFrame({
            "ts_code": ["300001.SZ", "300001.SZ"],
            "trade_date": ["20240101", "20240102"],
            "open": [20.0, 10.0],
            "high": [20.0, 10.0],
            "low": [20.0, 10.0],
            "close": [20.0, 10.0],
            "pre_close": [20.0, 10.0],
            "vol": [1000, 1000],
        })
        adj = pd.DataFrame({
            "ts_code": ["300001.SZ", "300001.SZ"],
            "trade_date": ["20240101", "20240102"],
            "adj_factor": [0.5, 1.0],
        })

        result = apply_adjusted_prices(daily, adj)

        assert result.loc[0, "close"] == pytest.approx(10.0)
        assert result.loc[1, "close"] == pytest.approx(10.0)
        assert result["vol"].tolist() == [1000, 1000]
