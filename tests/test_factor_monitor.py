"""Tests for src/factors/monitor.py — FactorMonitor.

Uses synthetic IC DataFrames to verify:
    1. Healthy factor (IC_IR > 0.3) → status="healthy"
    2. Degraded factor (IC_IR < 0.3 for 20+ days) → watchlist trigger
    3. High correlation between two factors → correlation warning
"""

from datetime import date

import numpy as np
import pandas as pd

from src.factors.monitor import (
    _correlation_warnings,
    _count_consecutive_low_ir,
    _pairwise_correlations,
    _rolling_ic_summary,
    analyze_factor_health,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ic_df(
    factor_data: dict[str, list[float | None]],
    start: str = "2025-01-01",
) -> pd.DataFrame:
    """Build a minimal IC DataFrame from explicit per-factor lists."""
    dates = pd.bdate_range(start, periods=len(next(iter(factor_data.values()))))
    data = {"trade_date": dates}
    data.update(factor_data)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# _rolling_ic_summary
# ---------------------------------------------------------------------------

def test_rolling_ic_summary_healthy():
    """A factor with stable positive IC should have IC_IR > 0.3."""
    # Generate consistent positive IC values
    rng = np.random.RandomState(42)
    ic_vals = list(rng.normal(0.05, 0.08, 80))  # mean=0.05, std~0.08 → IR~0.6
    df = _make_ic_df({"alpha": ic_vals})
    stats = _rolling_ic_summary(df, "alpha", window=60)

    assert stats["ic_mean"] is not None
    assert stats["ic_mean"] > 0
    assert stats["ic_ir"] is not None
    assert stats["ic_ir"] > 0.3
    assert stats["coverage"] == 1.0


def test_rolling_ic_summary_degraded():
    """A factor with near-zero IC should have IC_IR close to 0."""
    rng = np.random.RandomState(99)
    ic_vals = list(rng.normal(0.0, 0.5, 80))
    df = _make_ic_df({"noise": ic_vals})
    stats = _rolling_ic_summary(df, "noise", window=60)

    assert stats["ic_mean"] is not None
    assert stats["ic_ir"] is not None
    assert abs(stats["ic_ir"]) < 0.5  # should be near zero


def test_rolling_ic_summary_all_nan():
    """All-NaN series returns None stats but 0.0 coverage."""
    df = _make_ic_df({"empty": [None] * 60})
    stats = _rolling_ic_summary(df, "empty", window=60)

    assert stats["ic_mean"] is None
    assert stats["ic_ir"] is None
    assert stats["coverage"] == 0.0


# ---------------------------------------------------------------------------
# _count_consecutive_low_ir
# ---------------------------------------------------------------------------

def test_count_consecutive_low_ir_stable():
    """Factor with stable IC above threshold → 0 degraded sessions."""
    rng = np.random.RandomState(42)
    ic_vals = list(rng.normal(0.05, 0.08, 80))
    df = _make_ic_df({"alpha": ic_vals})
    count = _count_consecutive_low_ir(df, "alpha", threshold=0.3)

    assert count == 0


def test_count_consecutive_low_ir_degraded():
    """Factor with near-zero IC throughout → many degraded sessions."""
    rng = np.random.RandomState(99)
    ic_vals = list(rng.normal(0.0, 0.5, 80))
    df = _make_ic_df({"noise": ic_vals})
    count = _count_consecutive_low_ir(df, "noise", threshold=0.3)

    assert count >= 20


# ---------------------------------------------------------------------------
# _pairwise_correlations / _correlation_warnings
# ---------------------------------------------------------------------------

def test_pairwise_correlations_identical():
    """Identical factors should have correlation ~1.0."""
    vals = [0.01, 0.02, -0.01, 0.03, 0.0] * 16  # 80 points
    df = _make_ic_df({"f1": vals, "f2": vals})
    corr = _pairwise_correlations(df, ["f1", "f2"])
    assert abs(corr.loc["f1", "f2"] - 1.0) < 1e-10


def test_correlation_warnings_detects_high():
    """Warnings should be emitted for pairs with |corr| > threshold."""
    corr = pd.DataFrame(
        {"a": [1.0, 0.85], "b": [0.85, 1.0]},
        index=["a", "b"],
    )
    warnings = _correlation_warnings(corr, threshold=0.7)
    assert len(warnings) == 1
    assert "a" in warnings[0] and "b" in warnings[0]


def test_correlation_warnings_ignores_low():
    """No warnings for pairs below threshold."""
    corr = pd.DataFrame(
        {"a": [1.0, 0.2], "b": [0.2, 1.0]},
        index=["a", "b"],
    )
    warnings = _correlation_warnings(corr, threshold=0.7)
    assert len(warnings) == 0


# ---------------------------------------------------------------------------
# analyze_factor_health — integration
# ---------------------------------------------------------------------------

def test_healthy_factor_no_watchlist():
    """A single healthy factor should produce no watchlist triggers."""
    rng = np.random.RandomState(42)
    ic_vals = list(rng.normal(0.05, 0.08, 80))
    df = _make_ic_df({"alpha": ic_vals})
    report = analyze_factor_health(
        df, run_id="test_001", as_of_date=date(2025, 4, 1)
    )

    assert report.version == "FactorHealthReportV1"
    assert len(report.entries) == 1
    assert report.entries[0].factor_name == "alpha"
    assert report.entries[0].status == "healthy"
    assert len(report.watchlist_triggers) == 0


def test_degraded_factor_triggers_watchlist():
    """A factor with IC_IR < 0.3 for 20+ sessions triggers a watchlist entry."""
    rng = np.random.RandomState(99)
    ic_vals = list(rng.normal(0.0, 0.5, 80))
    df = _make_ic_df({"noise": ic_vals})
    report = analyze_factor_health(
        df, run_id="test_002", as_of_date=date(2025, 4, 1)
    )

    entry = report.entries[0]
    assert entry.status == "degraded"
    assert "noise" in report.watchlist_triggers


def test_high_correlation_triggers_warning():
    """Two highly correlated factors produce a correlation warning trigger."""
    rng = np.random.RandomState(7)
    base = list(rng.normal(0.03, 0.06, 80))
    # Add tiny noise so not perfectly identical but still highly correlated
    noise = list(rng.normal(0.0, 0.003, 80))
    f1 = [b + n for b, n in zip(base, noise)]
    f2 = [b - n for b, n in zip(base, noise)]

    df = _make_ic_df({"momentum": f1, "trend": f2})
    report = analyze_factor_health(
        df, run_id="test_003", as_of_date=date(2025, 4, 1),
        correlation_threshold=0.7,
    )

    # Both should be healthy (not degraded), but correlation warning exists
    assert all(e.status == "healthy" for e in report.entries)
    assert len(report.watchlist_triggers) > 0
    assert any("correlation" in t.lower() for t in report.watchlist_triggers)


def test_mixed_scenario():
    """One healthy, one degraded, and a correlation trigger."""
    rng = np.random.RandomState(42)
    healthy_vals = list(rng.normal(0.05, 0.08, 80))  # IR > 0.3
    degraded_vals = list(rng.normal(0.0, 0.5, 80))    # IR ~ 0

    df = _make_ic_df({"alpha": healthy_vals, "junk": degraded_vals})
    report = analyze_factor_health(
        df, run_id="test_004", as_of_date=date(2025, 4, 1)
    )

    by_name = {e.factor_name: e for e in report.entries}
    assert by_name["alpha"].status == "healthy"
    assert by_name["junk"].status == "degraded"
    assert "junk" in report.watchlist_triggers


def test_single_factor_no_correlation_check():
    """With only one factor, correlation check is skipped gracefully."""
    rng = np.random.RandomState(42)
    ic_vals = list(rng.normal(0.05, 0.08, 80))
    df = _make_ic_df({"solo": ic_vals})
    report = analyze_factor_health(
        df, run_id="test_005", as_of_date=date(2025, 4, 1)
    )

    assert len(report.entries) == 1
    assert report.entries[0].status == "healthy"
    assert len(report.watchlist_triggers) == 0


def test_report_json_roundtrip():
    """FactorHealthReportV1 should serialize and deserialize correctly."""
    rng = np.random.RandomState(42)
    ic_vals = list(rng.normal(0.05, 0.08, 80))
    df = _make_ic_df({"alpha": ic_vals})
    report = analyze_factor_health(
        df, run_id="rt_001", as_of_date=date(2025, 4, 1)
    )

    json_str = report.model_dump_json()
    from src.schemas.factor import FactorHealthReportV1
    parsed = FactorHealthReportV1.model_validate_json(json_str)
    assert parsed.run_id == "rt_001"
    assert parsed.entries[0].factor_name == "alpha"
