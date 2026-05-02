"""Tests for src/data/pit.py — point-in-time filtering."""

import pandas as pd
import pytest

from src.data.pit import pit_filter


class TestPitFilter:
    def test_filters_by_disclosure_date(self):
        df = pd.DataFrame({
            "ts_code": ["A", "B", "C"],
            "disclosure_date": ["20230301", "20230401", "20230601"],
            "value": [10, 20, 30],
        })
        result = pit_filter(df, "20230415")
        assert list(result["ts_code"]) == ["A", "B"]

    def test_exact_boundary_included(self):
        df = pd.DataFrame({
            "ts_code": ["A", "B"],
            "disclosure_date": ["20230301", "20230301"],
            "value": [10, 20],
        })
        result = pit_filter(df, "20230301")
        assert len(result) == 2

    def test_missing_disclosure_date_raises(self):
        df = pd.DataFrame({
            "ts_code": ["A"],
            "ann_date": ["20230301"],
            "value": [10],
        })
        with pytest.raises(ValueError, match="disclosure_date"):
            pit_filter(df, "20230401")

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["ts_code", "disclosure_date", "value"])
        result = pit_filter(df, "20230401")
        assert result.empty
        assert list(result.columns) == ["ts_code", "disclosure_date", "value"]

    def test_returns_copy_not_mutate_original(self):
        df = pd.DataFrame({
            "ts_code": ["A", "B"],
            "disclosure_date": ["20230101", "20231201"],
            "value": [1, 2],
        })
        result = pit_filter(df, "20230601")
        assert len(df) == 2  # original unchanged
        assert len(result) == 1
