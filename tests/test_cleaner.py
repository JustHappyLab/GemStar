import pandas as pd
import numpy as np
from src.data.cleaner import filter_st, filter_new_stocks, filter_suspended, fill_missing_cross_section


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
        })
        result = filter_new_stocks(df, "20230401", min_days=60)
        assert list(result["ts_code"]) == ["old"]


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
