"""Tests for Phase 5 fetcher functions: report_rc and report_fy."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.fetcher import fetch_report_rc, fetch_report_fy


@pytest.fixture
def pro():
    return MagicMock()


SAMPLE_RC_DF = pd.DataFrame(
    {
        "ts_code": ["300001.SZ", "300001.SZ"],
        "report_date": ["20240115", "20240220"],
        "org_name": ["CICC", "Huatai"],
        "rating_name": ["Buy", "Overweight"],
        "target_price": [25.0, 23.5],
        "indv_indu_code": ["001", "001"],
    }
)

SAMPLE_FY_DF = pd.DataFrame(
    {
        "ts_code": ["300001.SZ", "300001.SZ"],
        "report_date": ["20240115", "20240220"],
        "org_name": ["CICC", "Huatai"],
        "eps_last": [0.50, 0.48],
        "eps_this": [0.65, 0.62],
        "eps_next": [0.80, 0.75],
        "rating_name": ["Buy", "Overweight"],
    }
)


class TestReportRc:
    def test_fetch_report_rc_calls_api(self, pro, tmp_path):
        pro.report_rc.return_value = SAMPLE_RC_DF.copy()
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_report_rc(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
        pro.report_rc.assert_called_once_with(
            ts_code="300001.SZ", start_date="20240101", end_date="20240301"
        )
        assert len(df) == 2
        assert list(df.columns) == [
            "ts_code", "report_date", "org_name", "rating_name", "target_price", "indv_indu_code"
        ]

    def test_fetch_report_rc_caches(self, pro, tmp_path):
        pro.report_rc.return_value = SAMPLE_RC_DF.copy()
        with patch("src.data.fetcher._rate_limit"):
            fetch_report_rc(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
            df2 = fetch_report_rc(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
        assert pro.report_rc.call_count == 1
        assert len(df2) == 2

    def test_fetch_report_rc_returns_empty_on_none(self, pro, tmp_path):
        pro.report_rc.return_value = None
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_report_rc(pro, "300001.SZ", cache_dir=str(tmp_path))
        assert df.empty
        assert list(df.columns) == [
            "ts_code", "report_date", "org_name", "rating_name", "target_price", "indv_indu_code"
        ]


class TestReportFy:
    def test_fetch_report_fy_calls_api(self, pro, tmp_path):
        pro.report_fy.return_value = SAMPLE_FY_DF.copy()
        with patch("src.data.fetcher._rate_limit"):
            df = fetch_report_fy(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
        pro.report_fy.assert_called_once_with(
            ts_code="300001.SZ", start_date="20240101", end_date="20240301"
        )
        assert len(df) == 2
        assert list(df.columns) == [
            "ts_code", "report_date", "org_name", "eps_last", "eps_this", "eps_next", "rating_name"
        ]

    def test_fetch_report_fy_caches(self, pro, tmp_path):
        pro.report_fy.return_value = SAMPLE_FY_DF.copy()
        with patch("src.data.fetcher._rate_limit"):
            fetch_report_fy(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
            df2 = fetch_report_fy(pro, "300001.SZ", "20240101", "20240301", cache_dir=str(tmp_path))
        assert pro.report_fy.call_count == 1
        assert len(df2) == 2
