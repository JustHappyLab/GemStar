from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from src.data.fetcher import (
    fetch_trade_calendar,
    fetch_stock_basic,
    fetch_index_daily,
    fetch_daily_basic,
    fetch_fina_indicator,
)


@pytest.fixture
def pro():
    return MagicMock()


class TestTradeCalendar:
    def test_returns_only_open_days(self, pro, tmp_path):
        pro.trade_cal.return_value = pd.DataFrame({
            "cal_date": ["20230101", "20230102", "20230103"],
            "is_open": [0, 1, 1],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_trade_calendar(pro, "20230101", "20230103", cache_dir=str(tmp_path))
        assert list(df.columns) == ["cal_date"]
        assert len(df) == 2
        assert "20230101" not in df["cal_date"].values

    def test_second_call_uses_cache(self, pro, tmp_path):
        pro.trade_cal.return_value = pd.DataFrame({
            "cal_date": ["20230102"], "is_open": [1],
        })
        with patch("src.data.fetcher._rate_limit"):
            fetch_trade_calendar(pro, "20230101", "20230103", cache_dir=str(tmp_path))
            fetch_trade_calendar(pro, "20230101", "20230103", cache_dir=str(tmp_path))
        assert pro.trade_cal.call_count == 1


class TestStockBasic:
    def test_filters_chinext(self, pro, tmp_path):
        pro.stock_basic.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ", "600001.SH", "301001.SZ", "000001.SZ"],
            "name": ["A", "B", "C", "D"],
            "list_date": ["20100101"] * 4,
            "delist_date": [None] * 4,
            "market": ["创业板", "主板", "创业板", "主板"],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_stock_basic(pro, cache_dir=str(tmp_path))
        assert set(df["ts_code"]) == {"300001.SZ", "301001.SZ"}


class TestIndexDaily:
    def test_columns_and_sort(self, pro, tmp_path):
        pro.index_daily.return_value = pd.DataFrame({
            "ts_code": ["399006.SZ"] * 2,
            "trade_date": ["20230102", "20230101"],
            "open": [1.0, 2.0], "high": [1.0, 2.0],
            "low": [1.0, 2.0], "close": [1.0, 2.0],
            "vol": [100, 200], "amount": [1000, 2000],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_index_daily(pro, "399006.SZ", "20230101", "20230102", cache_dir=str(tmp_path))
        assert df.iloc[0]["trade_date"] == "20230101"


class TestDailyBasic:
    def test_columns(self, pro, tmp_path):
        expected_cols = ["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate", "total_mv", "circ_mv"]
        pro.daily_basic.return_value = pd.DataFrame({c: [1] for c in expected_cols})
        with patch("src.data.fetcher._rate_limit"), patch("src.data.fetcher._split_monthly", return_value=[("20230101", "20230131")]):
            df = fetch_daily_basic(pro, "20230101", "20230131", cache_dir=str(tmp_path))
        assert list(df.columns) == expected_cols


class TestFinaIndicator:
    def test_columns(self, pro, tmp_path):
        expected_cols = ["ts_code", "ann_date", "end_date", "roe", "revenue_yoy", "netprofit_yoy", "grossprofit_margin"]
        pro.fina_indicator.return_value = pd.DataFrame({c: ["x"] for c in expected_cols})
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_fina_indicator(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert list(df.columns) == expected_cols
