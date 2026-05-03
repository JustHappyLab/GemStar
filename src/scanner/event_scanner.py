"""EventScanner — event-driven signal detection via LLM.

CALLING SPEC:
    scan_events(data, reference_date, llm_client) -> list[SignalEventV1]

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via llm_client).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from src.llm.client import LLMClient
from src.schemas.signal import SignalEventV1

_SYSTEM_PROMPT = (Path(__file__).resolve().parents[2] / "skills" / "scan_events" / "prompt.txt").read_text(encoding="utf-8")


def _detect_earnings_surprise(data: dict[str, pd.DataFrame]) -> str:
    fina = data.get("fina_indicator")
    if fina is None or fina.empty or "netprofit_yoy" not in fina.columns:
        return "Earnings surprise: no fina_indicator data available."

    vals = fina["netprofit_yoy"].dropna().astype(float)
    if len(vals) < 2:
        return "Earnings surprise: insufficient data."

    mean = float(vals.mean())
    std = float(vals.std(ddof=1))
    outliers = vals[(vals - mean).abs() > 2 * std]

    if outliers.empty:
        return f"Earnings surprise: 0 stocks with netprofit_yoy >2σ from cross-sectional mean (μ={mean:.1f}%, σ={std:.1f}%)."

    codes = fina.loc[outliers.index, "ts_code"].tolist()
    magnitudes = [f"{v:+.1f}%" for v in outliers.values]
    pairs = [f"{c} ({m})" for c, m in zip(codes, magnitudes)]
    return (
        f"Earnings surprise: {len(outliers)} stock(s) with netprofit_yoy >2σ from "
        f"cross-sectional mean (μ={mean:.1f}%, σ={std:.1f}%): {', '.join(pairs)}."
    )


def _detect_volume_anomaly(data: dict[str, pd.DataFrame]) -> str:
    daily = data.get("daily")
    if daily is None or daily.empty:
        return "Volume anomaly: no daily data available."

    df = daily[["ts_code", "trade_date", "vol"]].copy()
    df["vol"] = df["vol"].astype(float)
    df["ma20"] = df.groupby("ts_code")["vol"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    latest = df.sort_values("trade_date").groupby("ts_code").tail(1)
    anomalies = latest[latest["vol"] > 3 * latest["ma20"]]

    if anomalies.empty:
        return "Volume anomaly: 0 stocks with volume >3x 20-day MA on the most recent day."

    pairs = [f"{r.ts_code} ({r.vol / r.ma20:.1f}x)" for r in anomalies.itertuples()]
    return f"Volume anomaly: {len(anomalies)} stock(s) with volume >3x 20-day MA: {', '.join(pairs)}."


def _detect_momentum_shift(data: dict[str, pd.DataFrame]) -> str:
    daily = data.get("daily")
    if daily is None or daily.empty:
        return "Momentum shift: no daily data available."

    df = daily[["ts_code", "trade_date", "close"]].copy().sort_values(["ts_code", "trade_date"])
    df["close"] = df["close"].astype(float)
    df["ret_5d"] = df.groupby("ts_code")["close"].pct_change(5)
    df["ret_20d"] = df.groupby("ts_code")["close"].pct_change(20)

    latest = df.sort_values("trade_date").groupby("ts_code").tail(1).copy()
    latest["mu_20d"] = latest["ret_20d"]
    std_20d = df.groupby("ts_code")["ret_20d"].std()

    anomalies: list[str] = []
    for idx, row in latest.iterrows():
        code = row["ts_code"]
        sigma = std_20d.get(code)
        if sigma is None or pd.isna(sigma) or sigma < 1e-9:
            continue
        z = abs(row["ret_5d"] - row["ret_20d"]) / sigma
        if z > 2:
            anomalies.append(f"{code} (z={z:.2f})")

    if not anomalies:
        return "Momentum shift: 0 stocks with 5-day return >2σ from 20-day distribution."

    return f"Momentum shift: {len(anomalies)} stock(s) deviating >2σ: {', '.join(anomalies)}."


def scan_events(
    data: dict[str, pd.DataFrame],
    reference_date: str,
    llm_client: LLMClient,
) -> list[SignalEventV1]:
    """Detect quantitative signals and return LLM-structured events.

    Args:
        data: Mapping of Tushare table name to DataFrame.
        reference_date: Current trading date as YYYYMMDD.
        llm_client: LLM client instance.

    Returns:
        List of validated SignalEventV1 events (may be empty).

    Raises:
        ValueError: If the LLM response cannot be parsed as valid events.
    """
    summary_parts = [
        _detect_earnings_surprise(data),
        _detect_volume_anomaly(data),
        _detect_momentum_shift(data),
    ]
    data_summary = "\n".join(summary_parts)
    user_prompt = f"Reference date: {reference_date}\n\nDetected quantitative signals:\n{data_summary}"

    system_prompt = _SYSTEM_PROMPT
    raw = llm_client.generate(user_prompt, system=system_prompt)

    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

    return [SignalEventV1.model_validate(item) for item in parsed]
