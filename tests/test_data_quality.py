"""Tests for DataQualityGate: freshness, completeness, PIT checks.

CALLING SPEC:
    Uses synthetic DataFrames — no Tushare calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data_quality.gate import (
    CORE_TABLES,
    OPTIONAL_TABLES,
    DataQualityReport,
    run_data_quality_gate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade_cal(dates: list[str], is_open: int = 1) -> pd.DataFrame:
    """Build a minimal trade_cal DataFrame."""
    return pd.DataFrame({
        "cal_date": dates,
        "is_open": [is_open] * len(dates),
    })


def _make_daily(ts_codes: list[str], trade_date: str, n_rows: int = 5) -> pd.DataFrame:
    """Build a minimal daily-bars DataFrame."""
    codes = ts_codes * (n_rows // len(ts_codes) + 1)
    return pd.DataFrame({
        "ts_code": codes[:n_rows],
        "trade_date": [trade_date] * n_rows,
        "open": [10.0] * n_rows,
        "high": [11.0] * n_rows,
        "low": [9.0] * n_rows,
        "close": [10.5] * n_rows,
        "vol": [1000.0] * n_rows,
    })


def _make_daily_basic(trade_date: str, n_rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "ts_code": [f"30000{i}.SZ" for i in range(n_rows)],
        "trade_date": [trade_date] * n_rows,
        "pe_ttm": [30.0] * n_rows,
        "pb": [3.5] * n_rows,
        "turnover_rate": [2.1] * n_rows,
        "total_mv": [1e9] * n_rows,
        "circ_mv": [5e8] * n_rows,
    })


def _make_adj_factor(trade_date: str, n_rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "ts_code": [f"30000{i}.SZ" for i in range(n_rows)],
        "trade_date": [trade_date] * n_rows,
        "adj_factor": [1.0] * n_rows,
    })


def _make_stock_basic(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "ts_code": [f"30000{i}.SZ" for i in range(n)],
        "name": [f"Stock{i}" for i in range(n)],
        "list_date": ["20100101"] * n,
    })


def _make_fina_indicator(
    disclosure_date: str | None = None,
    n_rows: int = 3,
) -> pd.DataFrame:
    """Build a fina_indicator DataFrame.

    If disclosure_date is None, the column is omitted.
    """
    data: dict = {
        "ts_code": [f"30000{i}.SZ" for i in range(n_rows)],
        "ann_date": ["20260430"] * n_rows,
        "end_date": ["20260331"] * n_rows,
        "roe": [12.0] * n_rows,
    }
    if disclosure_date is not None:
        data["disclosure_date"] = [disclosure_date] * n_rows
    return pd.DataFrame(data)


def _full_core_data(ref_date: str) -> dict[str, pd.DataFrame]:
    """Return a dict with all core tables present, up to ref_date."""
    return {
        "trade_cal": _make_trade_cal([ref_date]),
        "stock_basic": _make_stock_basic(),
        "daily": _make_daily(["300001.SZ", "300002.SZ", "300003.SZ"], ref_date),
        "daily_basic": _make_daily_basic(ref_date),
        "adj_factor": _make_adj_factor(ref_date),
        "fina_indicator": _make_fina_indicator(disclosure_date=ref_date),
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestNormalMode:
    """All core data present, fresh, no PIT violations → mode=normal."""

    def test_all_core_present_and_fresh(self):
        ref = "20260503"
        data = _full_core_data(ref)
        report = run_data_quality_gate(data, ref)

        assert report.mode == "normal"
        assert report.reference_date == ref
        assert len(report.core_tables_missing) == 0
        assert set(report.core_tables_present) == CORE_TABLES
        # No error or warning issues.
        assert all(i.level != "error" for i in report.issues)

    def test_with_optional_data_present(self):
        ref = "20260503"
        data = _full_core_data(ref)
        data["forecast"] = pd.DataFrame({"ts_code": ["300001.SZ"], "ann_date": [ref]})
        data["express"] = pd.DataFrame({"ts_code": ["300001.SZ"], "ann_date": [ref]})
        report = run_data_quality_gate(data, ref)

        assert report.mode == "normal"
        assert "forecast" in report.optional_tables_present
        assert "express" in report.optional_tables_present


class TestAbortMode:
    """Core data missing or severe staleness → mode=abort."""

    def test_core_table_missing_daily(self):
        ref = "20260503"
        data = _full_core_data(ref)
        del data["daily"]
        report = run_data_quality_gate(data, ref)

        assert report.mode == "abort"
        assert "daily" in report.core_tables_missing
        assert any(i.check == "missing" and i.table == "daily" for i in report.issues)

    def test_core_table_empty_dataframe(self):
        ref = "20260503"
        data = _full_core_data(ref)
        data["daily"] = pd.DataFrame(columns=["ts_code", "trade_date"])
        report = run_data_quality_gate(data, ref)

        assert report.mode == "abort"
        assert "daily" in report.core_tables_missing

    def test_core_table_none(self):
        ref = "20260503"
        data = _full_core_data(ref)
        data["stock_basic"] = None  # type: ignore[assignment]
        report = run_data_quality_gate(data, ref)

        assert report.mode == "abort"
        assert "stock_basic" in report.core_tables_missing

    def test_severely_stale_daily(self):
        """Last date > 10 calendar days old → abort."""
        ref = "20260503"
        stale_date = "20260420"  # 13 calendar days before ref
        data = _full_core_data(ref)
        data["daily"] = _make_daily(["300001.SZ"], stale_date)
        data["daily_basic"] = _make_daily_basic(stale_date)
        data["adj_factor"] = _make_adj_factor(stale_date)
        # No trade_cal so it falls back to calendar days.
        data.pop("trade_cal", None)
        report = run_data_quality_gate(data, ref)

        assert report.mode == "abort"
        assert any(i.check == "freshness" and i.level == "error" for i in report.issues)

    def test_empty_data_dict(self):
        report = run_data_quality_gate({}, "20260503")
        assert report.mode == "abort"
        assert len(report.core_tables_missing) == len(CORE_TABLES)


class TestDegradedMode:
    """Optional data missing or mild staleness → mode=degraded."""

    def test_optional_tables_missing(self):
        ref = "20260503"
        data = _full_core_data(ref)
        # No optional tables present.
        report = run_data_quality_gate(data, ref)

        # All core present → not abort.  But missing optionals are warnings.
        assert report.mode == "normal"  # missing optionals are warnings, not errors
        assert len(report.optional_tables_missing) == len(OPTIONAL_TABLES)

    def test_mildly_stale_daily(self):
        """Last date 7 calendar days old → degraded (via trade_cal)."""
        ref = "20260503"
        stale_date = "20260427"  # 6 calendar days, let's use trade_cal to make it 7 trading days.
        data = _full_core_data(ref)
        data["daily"] = _make_daily(["300001.SZ"], stale_date)
        data["daily_basic"] = _make_daily_basic(stale_date)
        data["adj_factor"] = _make_adj_factor(stale_date)
        # Provide trade_cal with 8 trading days between stale_date and ref.
        trading_days = [
            "20260427", "20260428", "20260429", "20260430",
            "20260501", "20260502", "20260503",
        ]
        data["trade_cal"] = _make_trade_cal(trading_days)
        report = run_data_quality_gate(data, ref)

        assert report.mode == "degraded"
        assert any(i.check == "freshness" and i.level == "warning" for i in report.issues)

    def test_optional_missing_does_not_force_abort(self):
        """Even if many optionals are missing, mode stays normal/degraded, not abort."""
        ref = "20260503"
        data = _full_core_data(ref)
        report = run_data_quality_gate(data, ref)

        # Optionals are all missing, but that only produces warnings.
        # With no warnings on core, mode should be normal.
        assert report.mode in ("normal", "degraded")


class TestPITCheck:
    """disclosure_date > reference_date is a PIT violation."""

    def test_no_disclosure_date_column(self):
        """If fina_indicator has no disclosure_date column, no PIT error."""
        ref = "20260503"
        data = _full_core_data(ref)
        data["fina_indicator"] = _make_fina_indicator(disclosure_date=None)
        report = run_data_quality_gate(data, ref)

        pit_issues = [i for i in report.issues if i.check == "pit"]
        assert len(pit_issues) == 0

    def test_disclosure_date_in_future(self):
        """Rows with disclosure_date > reference_date trigger PIT error."""
        ref = "20260503"
        data = _full_core_data(ref)
        # 2 rows OK, 1 row with future disclosure.
        fina = pd.DataFrame({
            "ts_code": ["300001.SZ", "300002.SZ", "300003.SZ"],
            "ann_date": ["20260430"] * 3,
            "end_date": ["20260331"] * 3,
            "roe": [12.0, 13.0, 14.0],
            "disclosure_date": ["20260401", "20260401", "20260601"],
        })
        data["fina_indicator"] = fina
        report = run_data_quality_gate(data, ref)

        pit_issues = [i for i in report.issues if i.check == "pit"]
        assert len(pit_issues) == 1
        assert "1 rows" in pit_issues[0].message

    def test_disclosure_date_exactly_on_ref_date(self):
        """disclosure_date == reference_date is OK (not a violation)."""
        ref = "20260503"
        data = _full_core_data(ref)
        data["fina_indicator"] = _make_fina_indicator(disclosure_date=ref)
        report = run_data_quality_gate(data, ref)

        pit_issues = [i for i in report.issues if i.check == "pit"]
        assert len(pit_issues) == 0


class TestEdgeCases:
    """Boundary conditions."""

    def test_report_is_json_serializable(self):
        import json

        ref = "20260503"
        data = _full_core_data(ref)
        report = run_data_quality_gate(data, ref)

        # Pydantic model_dump_json should work.
        j = report.model_dump_json()
        parsed = DataQualityReport.model_validate_json(j)
        assert parsed.mode == report.mode
        # json.loads should also work.
        raw = json.loads(j)
        assert raw["mode"] == "normal"

    def test_none_values_in_data_dict(self):
        """None values in data dict are treated as missing."""
        ref = "20260503"
        data: dict = {
            "trade_cal": _make_trade_cal([ref]),
            "stock_basic": None,
            "daily": None,
            "daily_basic": None,
            "adj_factor": None,
            "fina_indicator": None,
        }
        report = run_data_quality_gate(data, ref)
        assert report.mode == "abort"

    def test_freshness_with_trade_cal(self):
        """When trade_cal is present, staleness is counted in trading days."""
        ref = "20260503"
        # daily last date is 20260502, trade_cal has 20260502 and 20260503 → 1 trading day stale.
        data = _full_core_data(ref)
        data["daily"] = _make_daily(["300001.SZ"], "20260502")
        data["daily_basic"] = _make_daily_basic("20260502")
        data["adj_factor"] = _make_adj_factor("20260502")
        data["trade_cal"] = _make_trade_cal(["20260502", "20260503"])
        report = run_data_quality_gate(data, ref)

        # 1 trading day stale is fine.
        assert report.mode == "normal"

    def test_all_tables_present_including_optionals(self):
        ref = "20260503"
        data = _full_core_data(ref)
        # Add all optional tables.
        for tbl in OPTIONAL_TABLES:
            data[tbl] = pd.DataFrame({"ts_code": ["300001.SZ"], "trade_date": [ref]})
        report = run_data_quality_gate(data, ref)

        assert report.mode == "normal"
        assert len(report.optional_tables_missing) == 0
