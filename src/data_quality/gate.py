"""DataQualityGate: freshness / completeness / PIT checks on fetched DataFrames.

CALLING SPEC:
    run_data_quality_gate(data: dict[str, pd.DataFrame], reference_date: str) -> DataQualityReport
    - `data` keys are Tushare table names (e.g. "trade_cal", "daily", "fina_indicator").
    - `reference_date` is the current trading date in YYYYMMDD format.
    - Returns a DataQualityReport with mode ∈ {normal, degraded, abort} and a list of issues.
    - No Tushare calls are made; the gate only inspects already-fetched DataFrames.

SIDE EFFECTS:
    None.  Pure function.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data classification per Opus plan §7
# ---------------------------------------------------------------------------

CORE_TABLES: set[str] = {
    "trade_cal",
    "stock_basic",
    "daily",
    "daily_basic",
    "adj_factor",
    "fina_indicator",
}

OPTIONAL_TABLES: set[str] = {
    "forecast",
    "express",
    "news",
    "major_news",
    "anns_d",
    "moneyflow",
    "moneyflow_ind",
    "moneyflow_detail",
    "top_list",
    "limit_list_d",
    "research_report",
    "report_rc",
    "report_fy",
    "irm_qa",
    "irm_qa_his",
}

# Minimum row count for a non-empty table to be considered "present".
_MIN_ROWS = 1

# Staleness thresholds (trading days).  >5 → degraded; >10 → abort.
_STALE_DEGRADED_DAYS = 5
_STALE_ABORT_DAYS = 10


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DataQualityIssue(BaseModel):
    """A single quality finding."""

    level: Literal["warning", "error"]
    table: str
    check: Literal["freshness", "pit", "missing"]
    message: str


class DataQualityReport(BaseModel):
    """Structured output of DataQualityGate (Opus plan §7)."""

    version: Literal["DataQualityReportV1"] = "DataQualityReportV1"
    reference_date: str
    mode: Literal["normal", "degraded", "abort"]
    issues: list[DataQualityIssue] = Field(default_factory=list)
    core_tables_present: list[str] = Field(default_factory=list)
    core_tables_missing: list[str] = Field(default_factory=list)
    optional_tables_present: list[str] = Field(default_factory=list)
    optional_tables_missing: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_present(df: pd.DataFrame | None) -> bool:
    """A DataFrame is considered present if it is not None and has rows."""
    return df is not None and len(df) >= _MIN_ROWS


def _parse_yyyymmdd(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d")


def _check_freshness(
    data: dict[str, pd.DataFrame],
    reference_date: str,
    issues: list[DataQualityIssue],
) -> None:
    """Check that the last date in key tables is close to reference_date.

    Uses trade_cal (if available) to determine staleness in trading days.
    Falls back to calendar-day difference when trade_cal is absent.
    """
    ref_dt = _parse_yyyymmdd(reference_date)

    # Build a set of known trading dates from trade_cal if available.
    trading_dates: list[str] | None = None
    if "trade_cal" in data and _is_present(data["trade_cal"]):
        cal = data["trade_cal"]
        col = "cal_date" if "cal_date" in cal.columns else "trade_date"
        if "is_open" in cal.columns:
            open_days = cal[cal["is_open"] == 1][col].astype(str).sort_values().tolist()
        else:
            open_days = cal[col].astype(str).sort_values().tolist()
        trading_dates = open_days

    # Tables whose staleness we care about.
    freshness_tables = {"daily", "daily_basic", "adj_factor"}

    for tbl_name in freshness_tables:
        df = data.get(tbl_name)
        if not _is_present(df):
            continue  # missing is handled by completeness check

        # Determine the last date column.
        date_col: str | None = None
        for candidate in ("trade_date", "cal_date", "ann_date"):
            if candidate in df.columns:
                date_col = candidate
                break
        if date_col is None:
            continue  # no date column we recognise

        last_val = str(df[date_col].astype(str).sort_values().iloc[-1])
        try:
            last_dt = _parse_yyyymmdd(last_val)
        except ValueError:
            continue

        # Compute staleness.
        if trading_dates is not None and reference_date in trading_dates:
            # Count trading days between last_date and reference_date.
            recent = [d for d in trading_dates if d >= last_val and d <= reference_date]
            stale_trading_days = max(0, len(recent) - 1)
        else:
            # Fallback: calendar days.
            stale_trading_days = max(0, (ref_dt - last_dt).days)

        if stale_trading_days > _STALE_ABORT_DAYS:
            issues.append(DataQualityIssue(
                level="error",
                table=tbl_name,
                check="freshness",
                message=(
                    f"Last date {last_val} is {stale_trading_days} trading days "
                    f"before reference_date {reference_date} (>{_STALE_ABORT_DAYS} → abort)."
                ),
            ))
        elif stale_trading_days > _STALE_DEGRADED_DAYS:
            issues.append(DataQualityIssue(
                level="warning",
                table=tbl_name,
                check="freshness",
                message=(
                    f"Last date {last_val} is {stale_trading_days} trading days "
                    f"before reference_date {reference_date} (>{_STALE_DEGRADED_DAYS} → degraded)."
                ),
            ))


def _check_completeness(
    data: dict[str, pd.DataFrame],
    issues: list[DataQualityIssue],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Classify tables as present/missing for core and optional categories."""
    core_present: list[str] = []
    core_missing: list[str] = []
    opt_present: list[str] = []
    opt_missing: list[str] = []

    for tbl in sorted(CORE_TABLES):
        if _is_present(data.get(tbl)):
            core_present.append(tbl)
        else:
            core_missing.append(tbl)
            issues.append(DataQualityIssue(
                level="error",
                table=tbl,
                check="missing",
                message=f"Core table '{tbl}' is missing or empty.",
            ))

    for tbl in sorted(OPTIONAL_TABLES):
        if _is_present(data.get(tbl)):
            opt_present.append(tbl)
        else:
            opt_missing.append(tbl)
            issues.append(DataQualityIssue(
                level="warning",
                table=tbl,
                check="missing",
                message=f"Optional table '{tbl}' is missing or empty.",
            ))

    return core_present, core_missing, opt_present, opt_missing


def _check_pit(
    data: dict[str, pd.DataFrame],
    reference_date: str,
    issues: list[DataQualityIssue],
) -> None:
    """Point-in-Time check: financials must not have disclosure_date > reference_date.

    Per Opus plan §7: only use rows where disclosure_date <= t.
    """
    fina = data.get("fina_indicator")
    if not _is_present(fina):
        return

    if "disclosure_date" not in fina.columns:
        return  # column absent — nothing to check

    # disclosure_date may be YYYYMMDD string, int, or NaN.
    disc = fina["disclosure_date"].dropna().astype(str)
    # Strip any time component if present.
    disc = disc.str[:8]

    future_mask = disc > reference_date
    n_future = int(future_mask.sum())
    if n_future > 0:
        issues.append(DataQualityIssue(
            level="error",
            table="fina_indicator",
            check="pit",
            message=(
                f"{n_future} rows in fina_indicator have disclosure_date "
                f">{reference_date} — these would cause look-ahead bias."
            ),
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_data_quality_gate(
    data: dict[str, pd.DataFrame | None],
    reference_date: str,
) -> DataQualityReport:
    """Run all quality checks and return a structured report.

    Args:
        data: Mapping of table name → DataFrame (may contain None for missing).
        reference_date: Current trading date as YYYYMMDD.

    Returns:
        DataQualityReport with mode and issues.
    """
    # Normalise None values.
    clean_data: dict[str, pd.DataFrame] = {
        k: v for k, v in data.items() if v is not None
    }

    issues: list[DataQualityIssue] = []

    # 1. Completeness (must run first — determines mode floor).
    core_present, core_missing, opt_present, opt_missing = _check_completeness(
        clean_data, issues,
    )

    # 2. Freshness.
    _check_freshness(clean_data, reference_date, issues)

    # 3. PIT.
    _check_pit(clean_data, reference_date, issues)

    # --- Determine mode ---
    # Missing optionals are informational and do NOT degrade the mode.
    # Only freshness staleness and PIT violations on present data degrade.
    has_freshness_or_pit = any(i.check in ("freshness", "pit") for i in issues)
    has_freshness_error = any(
        i.check == "freshness" and i.level == "error" for i in issues
    )

    if core_missing or has_freshness_error:
        mode: Literal["normal", "degraded", "abort"] = "abort"
    elif has_freshness_or_pit:
        mode = "degraded"
    else:
        mode = "normal"

    return DataQualityReport(
        reference_date=reference_date,
        mode=mode,
        issues=issues,
        core_tables_present=core_present,
        core_tables_missing=core_missing,
        optional_tables_present=opt_present,
        optional_tables_missing=opt_missing,
    )
