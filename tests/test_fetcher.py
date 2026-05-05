from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from src.data.fetcher import (
    _call_with_retry,
    _normalize_fina_indicator,
    init_tushare,
    fetch_trade_calendar,
    fetch_stock_basic,
    fetch_index_daily,
    fetch_daily_basic,
    fetch_fina_indicator,
)
from requests.exceptions import ChunkedEncodingError


@pytest.fixture
def pro():
    return MagicMock()


class TestInitTushare:
    def test_raises_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
        with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
            init_tushare()

    def test_prefers_explicit_token(self, monkeypatch):
        monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
        fake_pro = object()
        with patch("src.data.fetcher.ts.set_token") as set_token, patch(
            "src.data.fetcher.ts.pro_api", return_value=fake_pro
        ):
            pro = init_tushare(" explicit-token ")
        set_token.assert_called_once_with("explicit-token")
        assert pro is fake_pro


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


class TestRetryHelper:
    def test_retries_request_exception_and_succeeds(self):
        fetch_fn = MagicMock(
            side_effect=[
                ChunkedEncodingError("broken"),
                pd.DataFrame({"cal_date": ["20230102"], "is_open": [1]}),
            ]
        )
        with patch("src.data.fetcher.time.sleep"):
            result = _call_with_retry(fetch_fn, op_name="daily 20230102")
        assert len(result) == 1
        assert fetch_fn.call_count == 2


class TestFinaNormalization:
    def test_renames_or_yoy_to_revenue_yoy(self):
        df = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "end_date": ["20231231"],
            "roe": [12.0],
            "or_yoy": [18.5],
            "netprofit_yoy": [8.0],
            "grossprofit_margin": [21.0],
        })
        normalized = _normalize_fina_indicator(df)
        assert "revenue_yoy" in normalized.columns
        assert "disclosure_date" in normalized.columns
        assert normalized.loc[0, "revenue_yoy"] == 18.5
        assert normalized.loc[0, "disclosure_date"] == "20240101"


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
        expected_cols = ["ts_code", "ann_date", "disclosure_date", "end_date", "roe", "revenue_yoy", "netprofit_yoy", "grossprofit_margin"]
        pro.fina_indicator.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "end_date": ["20231231"],
            "roe": [12.0],
            "or_yoy": [18.5],
            "netprofit_yoy": [8.0],
            "grossprofit_margin": [21.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_fina_indicator(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert list(df.columns) == expected_cols

    def test_refetches_legacy_cache_without_revenue_yoy(self, pro, tmp_path):
        legacy = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "end_date": ["20231231"],
            "roe": [12.0],
            "netprofit_yoy": [8.0],
            "grossprofit_margin": [21.0],
        })
        legacy.to_parquet(tmp_path / "fina_300001_SZ.parquet", index=False)
        pro.fina_indicator.return_value = pd.DataFrame({
            "ts_code": ["300001.SZ"],
            "ann_date": ["20240101"],
            "end_date": ["20231231"],
            "roe": [12.0],
            "or_yoy": [18.5],
            "netprofit_yoy": [8.0],
            "grossprofit_margin": [21.0],
        })
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_fina_indicator(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.loc[0, "revenue_yoy"] == 18.5
        assert pro.fina_indicator.call_count == 1
