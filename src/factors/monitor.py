"""Factor health monitor — rolling IC/IR, coverage, pairwise correlation.

CALLING SPEC:
    report = analyze_factor_health(
        ic_df=pd.DataFrame,       # trade_date + one col per factor
        run_id=str,
        as_of_date=date,
        window=60,
        ic_ir_threshold=0.3,
        ic_ir_degraded_days=20,
        correlation_threshold=0.7,
    ) -> FactorHealthReportV1

    Accepts a pre-computed daily IC DataFrame (output of
    src.ranker.ic.compute_daily_rank_ic) and produces a FactorHealthReportV1
    with per-factor health entries, coverage stats, and watchlist triggers.

SIDE EFFECTS:
    None — pure function.
"""

from datetime import date
from typing import Literal

import pandas as pd

from src.schemas.factor import FactorHealthEntry, FactorHealthReportV1


def _rolling_ir_series(series: pd.Series, window: int) -> pd.Series:
    """Compute rolling IR (= rolling_mean / rolling_std) for an IC series."""
    win = min(window, len(series))
    rolling_mean = series.rolling(window=win, min_periods=2).mean()
    rolling_std = series.rolling(window=win, min_periods=2).std()
    return (rolling_mean / rolling_std).replace(
        [float("inf"), float("nan")], 0.0
    )


def _rolling_ic_summary(
    ic_df: pd.DataFrame,
    factor_col: str,
    window: int,
) -> dict[str, float | None]:
    """Compute rolling-window IC stats for one factor.

    Returns dict with keys: ic_mean, ic_std, ic_ir, ic_positive_rate, coverage.
    """
    series = ic_df[factor_col].tail(window)
    valid = series.dropna()
    n_total = len(series)
    n_valid = len(valid)

    coverage = n_valid / n_total if n_total > 0 else 0.0
    if n_valid == 0:
        return {
            "ic_mean": None,
            "ic_std": None,
            "ic_ir": None,
            "ic_positive_rate": None,
            "coverage": coverage,
        }

    ic_mean = float(valid.mean())
    ic_std = float(valid.std())
    ic_ir = ic_mean / ic_std if ic_std != 0 else None
    ic_positive_rate = float((valid > 0).mean())

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ic_ir": ic_ir,
        "ic_positive_rate": ic_positive_rate,
        "coverage": coverage,
    }


def _count_consecutive_low_ir(
    ic_df: pd.DataFrame,
    factor_col: str,
    threshold: float,
    window: int = 60,
) -> int:
    """Count trailing consecutive sessions where rolling IC_IR < threshold."""
    series = ic_df[factor_col].dropna()
    if len(series) < 2:
        return 0

    rolling_ir = _rolling_ir_series(series, window)

    count = 0
    for val in reversed(rolling_ir.tolist()):
        if val < threshold:
            count += 1
        else:
            break
    return count


def _pairwise_correlations(
    ic_df: pd.DataFrame,
    factor_cols: list[str],
) -> pd.DataFrame:
    """Compute pairwise Pearson correlation matrix for factor IC time series."""
    return ic_df[factor_cols].corr()


def _correlation_warnings(
    corr_matrix: pd.DataFrame,
    threshold: float,
) -> list[str]:
    """Return list of warning strings for pairs with |correlation| > threshold."""
    warnings: list[str] = []
    cols = list(corr_matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            rho = corr_matrix.iloc[i, j]
            if abs(rho) > threshold:
                warnings.append(
                    f"High correlation ({rho:.3f}) between {cols[i]} and {cols[j]}"
                )
    return warnings


def _determine_status(
    ic_ir: float | None,
    degraded_sessions: int,
    degraded_threshold: int,
) -> Literal["healthy", "degraded", "critical"]:
    """Determine health status for a factor."""
    if ic_ir is None:
        return "critical"
    if degraded_sessions >= degraded_threshold:
        return "degraded"
    return "healthy"


def analyze_factor_health(
    ic_df: pd.DataFrame,
    run_id: str,
    as_of_date: date,
    *,
    window: int = 60,
    ic_ir_threshold: float = 0.3,
    ic_ir_degraded_days: int = 20,
    correlation_threshold: float = 0.7,
) -> FactorHealthReportV1:
    """Produce a FactorHealthReportV1 from a pre-computed daily IC DataFrame.

    Parameters
    ----------
    ic_df : DataFrame with ``trade_date`` column and one column per factor.
    run_id : Opaque run identifier.
    as_of_date : Date of the report.
    window : Rolling window size in sessions (default 60).
    ic_ir_threshold : Minimum acceptable IC_IR (default 0.3).
    ic_ir_degraded_days : Consecutive sessions below threshold before watchlist (default 20).
    correlation_threshold : Max acceptable |pairwise correlation| (default 0.7).
    """
    factor_cols = [c for c in ic_df.columns if c != "trade_date"]

    # --- per-factor stats ---
    entries: list[FactorHealthEntry] = []
    watchlist_triggers: list[str] = []

    for col in factor_cols:
        stats = _rolling_ic_summary(ic_df, col, window)
        degraded_sessions = _count_consecutive_low_ir(
            ic_df, col, ic_ir_threshold
        )
        status = _determine_status(
            stats["ic_ir"], degraded_sessions, ic_ir_degraded_days
        )

        note_parts: list[str] = []
        if status == "degraded":
            note_parts.append(
                f"IC_IR below {ic_ir_threshold} for {degraded_sessions} sessions"
            )
            watchlist_triggers.append(col)

        entries.append(
            FactorHealthEntry(
                factor_name=col,
                ic_mean=stats["ic_mean"],
                ic_ir=stats["ic_ir"],
                ic_positive_rate=stats["ic_positive_rate"],
                coverage=stats["coverage"],
                status=status,
                note="; ".join(note_parts) if note_parts else "",
            )
        )

    # --- pairwise correlation ---
    if len(factor_cols) >= 2:
        corr_matrix = _pairwise_correlations(ic_df, factor_cols)
        corr_warnings = _correlation_warnings(corr_matrix, correlation_threshold)
        for warning in corr_warnings:
            watchlist_triggers.append(warning)

    return FactorHealthReportV1(
        run_id=run_id,
        as_of_date=as_of_date,
        entries=entries,
        watchlist_triggers=watchlist_triggers,
    )
