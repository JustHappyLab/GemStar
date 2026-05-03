"""MacroAnalyst — market regime assessment via LLM.

CALLING SPEC:
    analyze_market_regime(daily_df, index_df, reference_date, llm_client) -> MarketRegimeV1

SIDE EFFECTS:
    Makes HTTP requests to the Anthropic API (via llm_client).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.llm.client import LLMClient
from src.schemas.signal import MarketRegimeV1

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "macro_analyst.txt"


def _compute_user_prompt(
    daily_df: pd.DataFrame,
    index_df: pd.DataFrame,
    reference_date: str,
) -> str:
    """Compute market stats and return a Chinese-language summary prompt."""
    dates = sorted(daily_df["trade_date"].unique())[-20:]
    window = daily_df[daily_df["trade_date"].isin(dates)].copy()

    window["daily_ret"] = (window["close"] - window["pre_close"]) / window["pre_close"]

    market_return: float = window["daily_ret"].mean()
    volatility: float = window["daily_ret"].std()
    breadth: float = (window["daily_ret"] > 0).mean()

    recent_dates = dates[-5:]
    prior_dates = dates[:-5]
    recent_vol = window[window["trade_date"].isin(recent_dates)]["vol"].mean()
    prior_vol = window[window["trade_date"].isin(prior_dates)]["vol"].mean()
    volume_trend = (recent_vol / prior_vol - 1) if prior_vol > 0 else 0.0

    idx_window = index_df[index_df["trade_date"].isin(dates)].sort_values("trade_date")
    idx_ret_20d = (
        (idx_window["close"].iloc[-1] / idx_window["close"].iloc[0] - 1)
        if len(idx_window) >= 2
        else 0.0
    )
    idx_daily_ret = idx_window["close"].pct_change().dropna()
    idx_volatility: float = idx_daily_ret.std() if len(idx_daily_ret) > 0 else 0.0

    return (
        f"参考日期: {reference_date}\n"
        f"市场收益: {market_return:+.2%}\n"
        f"波动率: {volatility:.2%}\n"
        f"上涨比例: {breadth:.1%}\n"
        f"成交量趋势(近5日/前15日): {volume_trend:+.1%}\n"
        f"创业板指20日收益: {idx_ret_20d:+.2%}\n"
        f"创业板指波动率: {idx_volatility:.2%}\n"
    )


def analyze_market_regime(
    daily_df: pd.DataFrame,
    index_df: pd.DataFrame,
    reference_date: str,
    llm_client: LLMClient,
) -> MarketRegimeV1:
    """Assess the current market regime from stock-level and index data.

    Args:
        daily_df: Daily stock data with columns ts_code, trade_date, close,
            pre_close, vol.  Must cover at least 20 trading days.
        index_df: ChiNext index daily data with columns trade_date, close.
        reference_date: Date string in YYYYMMDD format.
        llm_client: LLM client for generating the regime assessment.

    Returns:
        A validated MarketRegimeV1 instance.

    Raises:
        ValueError: If JSON parsing fails after all retries.
    """
    user_prompt = _compute_user_prompt(daily_df, index_df, reference_date)
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    last_exc: Exception | None = None
    for attempt in range(1, llm_client._max_retries + 1):
        try:
            response = llm_client.generate(user_prompt, system=system_prompt)
            return MarketRegimeV1.model_validate_json(response)
        except (ValueError, KeyError) as exc:
            last_exc = exc
            logger.warning(
                "Attempt %d/%d failed validation: %s",
                attempt,
                llm_client._max_retries,
                exc,
            )

    raise ValueError(
        f"Failed after {llm_client._max_retries} retries: {last_exc}"
    ) from last_exc
