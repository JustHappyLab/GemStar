"""Tests for src.scanner.macro_analyst — mocked LLM, no live API calls."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.scanner.macro_analyst import analyze_market_regime
from src.llm.client import LLMClient
from src.schemas.signal import MarketRegimeV1


def _make_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_daily_df(n_stocks: int = 10, n_days: int = 20) -> pd.DataFrame:
    codes = [f"30000{i}.SZ" for i in range(n_stocks)]
    dates = pd.bdate_range("20260401", periods=n_days).strftime("%Y%m%d").tolist()
    rows = []
    for code in codes:
        for d in dates:
            rows.append({
                "ts_code": code,
                "trade_date": d,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5 + np.random.randn() * 0.5,
                "pre_close": 10.0,
                "vol": 1000000.0,
            })
    return pd.DataFrame(rows)


def _make_index_df(n_days: int = 20) -> pd.DataFrame:
    dates = pd.bdate_range("20260401", periods=n_days).strftime("%Y%m%d").tolist()
    return pd.DataFrame({
        "trade_date": dates,
        "close": [1000.0 + i * 2 for i in range(n_days)],
        "open": [999.0 + i * 2 for i in range(n_days)],
        "high": [1001.0 + i * 2 for i in range(n_days)],
        "low": [998.0 + i * 2 for i in range(n_days)],
        "vol": [50000000.0] * n_days,
    })


def _valid_regime_json() -> str:
    return json.dumps({
        "version": "MarketRegimeV1",
        "as_of_date": "2026-04-30",
        "regime": "bullish",
        "confidence": 0.82,
        "key_drivers": ["成交量放大", "科技板块轮动"],
        "style_bias": "成长",
    })


@patch("src.llm.client.anthropic.Anthropic")
def test_valid_json_returns_market_regime(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(_valid_regime_json())

    llm = LLMClient(api_key="test-key")
    result = analyze_market_regime(
        _make_daily_df(), _make_index_df(), "20260430", llm,
    )

    assert isinstance(result, MarketRegimeV1)
    assert result.regime == "bullish"
    assert result.confidence == pytest.approx(0.82)
    assert result.key_drivers == ["成交量放大", "科技板块轮动"]
    assert result.style_bias == "成长"


@patch("src.llm.client.anthropic.Anthropic")
def test_as_of_date_matches_reference(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(_valid_regime_json())

    llm = LLMClient(api_key="test-key")
    result = analyze_market_regime(
        _make_daily_df(), _make_index_df(), "20260430", llm,
    )

    assert str(result.as_of_date) == "2026-04-30"


@patch("src.llm.client.anthropic.Anthropic")
def test_regime_is_valid_enum(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response(_valid_regime_json())

    llm = LLMClient(api_key="test-key")
    result = analyze_market_regime(
        _make_daily_df(), _make_index_df(), "20260430", llm,
    )

    assert result.regime in {"bullish", "bearish", "neutral", "volatile", "defensive"}


@patch("src.llm.client.anthropic.Anthropic")
def test_malformed_json_retries_then_raises(mock_anthropic_cls: MagicMock) -> None:
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_response("NOT VALID JSON")

    llm = LLMClient(max_retries=2, api_key="test-key")
    with pytest.raises(ValueError):
        analyze_market_regime(
            _make_daily_df(), _make_index_df(), "20260430", llm,
        )

    assert mock_client.messages.create.call_count == 2
