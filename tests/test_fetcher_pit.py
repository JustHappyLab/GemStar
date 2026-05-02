"""Tests for PIT-friendly fetcher functions in src/data/fetcher.py."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.fetcher import (
    fetch_income,
    fetch_balancesheet,
    fetch_cashflow,
    fetch_disclosure_date,
    fetch_forecast,
    fetch_express,
)


@pytest.fixture
def pro():
    return MagicMock()


# -- API dispatch tests -------------------------------------------------------

class TestFetchIncome:
    def test_calls_pro_income(self, pro, tmp_path):
        pro.income.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "end_date": ["20231231"],
            "revenue": [100.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_income(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.income.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1

    def test_caches_result(self, pro, tmp_path):
        pro.income.return_value = pd.DataFrame({"ts_code": ["300001.SZ"]})
        with patch("src.data.fetcher._rate_limit"):
            fetch_income(pro, "300001.SZ", cache_dir=str(tmp_path))
            fetch_income(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert pro.income.call_count == 1


class TestFetchBalancesheet:
    def test_calls_pro_balancesheet(self, pro, tmp_path):
        pro.balancesheet.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "total_assets": [500.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_balancesheet(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.balancesheet.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1


class TestFetchCashflow:
    def test_calls_pro_cashflow(self, pro, tmp_path):
        pro.cashflow.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "n_cashflow_act": [80.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_cashflow(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.cashflow.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1


class TestFetchDisclosureDate:
    def test_calls_pro_disclosure_date(self, pro, tmp_path):
        pro.disclosure_date.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "end_date": ["20231231"],
            "pre_date": ["20240301"],
            "actual_date": ["20240315"],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_disclosure_date(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.disclosure_date.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1


class TestFetchForecast:
    def test_calls_pro_forecast(self, pro, tmp_path):
        pro.forecast.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "type": ["预增"],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_forecast(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.forecast.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1


class TestFetchExpress:
    def test_calls_pro_express(self, pro, tmp_path):
        pro.express.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "revenue": [100.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_express(pro, "300001.SZ", cache_dir=str(tmp_path))
        pro.express.assert_called_once_with(ts_code="300001.SZ")
        assert len(df) == 1


# -- None-return guard tests --------------------------------------------------

class TestNoneHandling:
    """When Tushare returns None (e.g. no data), the fetcher should produce an
    empty DataFrame rather than crashing."""

    def test_income_none_returns_empty(self, pro, tmp_path):
        pro.income.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_income(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_balancesheet_none_returns_empty(self, pro, tmp_path):
        pro.balancesheet.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_balancesheet(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty

    def test_cashflow_none_returns_empty(self, pro, tmp_path):
        pro.cashflow.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_cashflow(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty

    def test_forecast_none_returns_empty(self, pro, tmp_path):
        pro.forecast.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_forecast(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty

    def test_express_none_returns_empty(self, pro, tmp_path):
        pro.express.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_express(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty

    def test_disclosure_date_none_returns_empty(self, pro, tmp_path):
        pro.disclosure_date.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_disclosure_date(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty
