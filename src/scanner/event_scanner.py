"""EventScanner — deterministic event-driven signal detection.

CALLING SPEC:
    scan_events(data, reference_date, llm_client) -> list[SignalEventV1]

SIDE EFFECTS:
    None. The llm_client argument is kept for pipeline compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt

import pandas as pd

from src.llm.adapter import LLMGenerate
from src.schemas.signal import SignalEventV1


@dataclass(frozen=True)
class _EventCandidate:
    event_type: str
    severity: str
    summary: str
    affected_symbols: list[str]
    source_refs: list[str]
    confidence: float
    recommended_next_action: str
    affected_sectors: list[str] | None = None


def _event_date(reference_date: str) -> str:
    return datetime.strptime(reference_date, "%Y%m%d").date().isoformat()


def _severity_from_score(score: float, medium: float, high: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _confidence_from_score(score: float, base: float = 0.58, step: float = 0.04) -> float:
    return round(min(0.92, max(0.0, base + score * step)), 2)


def _top_symbols(frame: pd.DataFrame, score_col: str, limit: int = 5) -> list[str]:
    if "ts_code" not in frame.columns or score_col not in frame.columns:
        return []
    return (
        frame.sort_values(score_col, ascending=False)["ts_code"]
        .astype(str)
        .drop_duplicates()
        .head(limit)
        .tolist()
    )


def _latest_fundamental_rows(frame: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [col for col in ("ann_date", "end_date") if col in frame.columns]
    if not sort_cols:
        return frame.drop_duplicates(subset=["ts_code"], keep="last")
    return frame.sort_values(["ts_code", *sort_cols]).drop_duplicates(subset=["ts_code"], keep="last")


def _detect_earnings_surprise(data: dict[str, pd.DataFrame]) -> _EventCandidate | None:
    fina = data.get("fina_indicator")
    if fina is None or fina.empty or "netprofit_yoy" not in fina.columns or "ts_code" not in fina.columns:
        return None

    df = _latest_fundamental_rows(fina)[["ts_code", "netprofit_yoy"]].copy()
    df["netprofit_yoy"] = pd.to_numeric(df["netprofit_yoy"], errors="coerce")
    df = df.dropna(subset=["netprofit_yoy"])
    if len(df) < 5:
        return None

    values = df["netprofit_yoy"]
    median = float(values.median())
    mad = float((values - median).abs().median())
    if mad > 1e-9:
        robust_sigma = 1.4826 * mad
        df["surprise_score"] = (values - median).abs() / robust_sigma
    else:
        std = float(values.std(ddof=0))
        if std <= 1e-9:
            return None
        mean = float(values.mean())
        df["surprise_score"] = (values - mean).abs() / std

    outliers = df[df["surprise_score"] >= 3.5].copy()
    if outliers.empty:
        return None

    outliers = outliers.sort_values("surprise_score", ascending=False)
    symbols = _top_symbols(outliers, "surprise_score")
    strongest = outliers.iloc[0]
    strongest_code = str(strongest["ts_code"])
    strongest_yoy = float(strongest["netprofit_yoy"])
    strongest_score = float(strongest["surprise_score"])
    severity = _severity_from_score(strongest_score, medium=3.5, high=6.0)

    return _EventCandidate(
        event_type="earnings_surprise",
        severity=severity,
        summary=(
            f"{len(outliers)} stocks show earnings outliers; "
            f"{strongest_code} netprofit_yoy {strongest_yoy:+.1f}% is strongest."
        ),
        affected_symbols=symbols,
        source_refs=["fina_indicator.netprofit_yoy"],
        confidence=_confidence_from_score(strongest_score, base=0.62, step=0.035),
        recommended_next_action="Review earnings-driven exposure and validate whether revisions are already priced.",
    )


def _detect_volume_anomaly(data: dict[str, pd.DataFrame]) -> _EventCandidate | None:
    daily = data.get("daily")
    required = {"ts_code", "trade_date", "vol"}
    if daily is None or daily.empty or not required.issubset(daily.columns):
        return None

    df = daily[list(required)].copy().sort_values(["ts_code", "trade_date"])
    df["vol"] = pd.to_numeric(df["vol"], errors="coerce")
    df = df.dropna(subset=["vol"])
    if df.empty:
        return None

    df["ma20_prev"] = df.groupby("ts_code")["vol"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=5).mean()
    )
    latest = df.groupby("ts_code", as_index=False).tail(1).copy()
    latest = latest[latest["ma20_prev"].notna() & (latest["ma20_prev"] > 0)]
    if latest.empty:
        return None

    latest["volume_ratio"] = latest["vol"] / latest["ma20_prev"]
    anomalies = latest[latest["volume_ratio"] >= 3.0].copy()
    if anomalies.empty:
        return None

    anomalies = anomalies.sort_values("volume_ratio", ascending=False)
    symbols = _top_symbols(anomalies, "volume_ratio")
    strongest = anomalies.iloc[0]
    strongest_code = str(strongest["ts_code"])
    strongest_ratio = float(strongest["volume_ratio"])
    severity = _severity_from_score(strongest_ratio, medium=3.0, high=5.0)

    return _EventCandidate(
        event_type="sentiment_shift",
        severity=severity,
        summary=(
            f"{len(anomalies)} stocks trade above 3x prior 20-day volume; "
            f"{strongest_code} is {strongest_ratio:.1f}x."
        ),
        affected_symbols=symbols,
        source_refs=["daily.vol"],
        confidence=_confidence_from_score(strongest_ratio, base=0.55, step=0.06),
        recommended_next_action="Check news, liquidity, and short-term crowding before adding exposure.",
    )


def _detect_momentum_shift(data: dict[str, pd.DataFrame]) -> _EventCandidate | None:
    daily = data.get("daily")
    required = {"ts_code", "trade_date", "close"}
    if daily is None or daily.empty or not required.issubset(daily.columns):
        return None

    df = daily[list(required)].copy().sort_values(["ts_code", "trade_date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    if df.empty:
        return None

    grouped = df.groupby("ts_code")
    df["ret_1d"] = grouped["close"].pct_change()
    df["ret_5d"] = grouped["close"].pct_change(5)
    df["vol20_prev"] = grouped["ret_1d"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).std())
    latest = df.groupby("ts_code", as_index=False).tail(1).copy()
    latest = latest.dropna(subset=["ret_5d", "vol20_prev"])
    latest = latest[latest["vol20_prev"] > 1e-9]
    if latest.empty:
        return None

    latest["momentum_z"] = latest["ret_5d"].abs() / (latest["vol20_prev"] * sqrt(5))
    anomalies = latest[latest["momentum_z"] >= 2.5].copy()
    if anomalies.empty:
        return None

    anomalies = anomalies.sort_values("momentum_z", ascending=False)
    symbols = _top_symbols(anomalies, "momentum_z")
    strongest = anomalies.iloc[0]
    strongest_code = str(strongest["ts_code"])
    strongest_z = float(strongest["momentum_z"])
    strongest_ret = float(strongest["ret_5d"])
    severity = _severity_from_score(strongest_z, medium=2.5, high=4.0)

    return _EventCandidate(
        event_type="factor_drift",
        severity=severity,
        summary=(
            f"{len(anomalies)} stocks show abnormal 5-day momentum; "
            f"{strongest_code} return {strongest_ret:+.1%}, z={strongest_z:.1f}."
        ),
        affected_symbols=symbols,
        source_refs=["daily.close"],
        confidence=_confidence_from_score(strongest_z, base=0.54, step=0.07),
        recommended_next_action="Inspect momentum factor exposure and rebalance if the move conflicts with regime bias.",
    )


def _build_events(candidates: list[_EventCandidate], reference_date: str) -> list[SignalEventV1]:
    date_value = _event_date(reference_date)
    events: list[SignalEventV1] = []
    for index, candidate in enumerate(candidates, start=1):
        events.append(
            SignalEventV1.model_validate(
                {
                    "version": "SignalEventV1",
                    "event_date": date_value,
                    "event_id": f"evt_{reference_date}_{index:03d}",
                    "event_type": candidate.event_type,
                    "severity": candidate.severity,
                    "summary": candidate.summary,
                    "affected_sectors": candidate.affected_sectors or [],
                    "affected_symbols": candidate.affected_symbols,
                    "source_refs": candidate.source_refs,
                    "confidence": candidate.confidence,
                    "recommended_next_action": candidate.recommended_next_action,
                }
            )
        )
    return events


def scan_events(
    data: dict[str, pd.DataFrame],
    reference_date: str,
    llm_client: LLMGenerate,
) -> list[SignalEventV1]:
    """Detect quantitative signals and return validated structured events.

    The llm_client parameter is intentionally unused. Earlier versions asked an
    LLM to translate detected signals into JSON, which made the pipeline fail on
    formatting noise. This scanner now owns the structured contract locally.
    """
    _ = llm_client
    candidates = [
        candidate
        for candidate in (
            _detect_earnings_surprise(data),
            _detect_volume_anomaly(data),
            _detect_momentum_shift(data),
        )
        if candidate is not None
    ]
    return _build_events(candidates, reference_date)
