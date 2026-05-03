"""Tests for src.scanner.event_scanner — mocked Anthropic API, no live requests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.llm.client import LLMClient
from src.schemas.signal import SignalEventV1
from src.scanner.event_scanner import scan_events


def _make_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def _make_data() -> dict[str, pd.DataFrame]:
    codes = [f"30000{i}.SZ" for i in range(5)]
    dates = pd.bdate_range("20260301", "20260501").strftime("%Y%m%d").tolist()
    daily_rows = []
    for code in codes:
        for d in dates:
            daily_rows.append({
                "ts_code": code, "trade_date": d,
                "open": 10.0, "high": 11.0, "low": 9.0,
                "close": 10.5 + np.random.randn() * 0.3,
                "pre_close": 10.0, "vol": 1000000.0,
            })
    fina = pd.DataFrame({
        "ts_code": codes,
        "ann_date": ["20260501"] * len(codes),
        "netprofit_yoy": [15.0, 20.0, -5.0, 8.0, 200.0],
    })
    return {"daily": pd.DataFrame(daily_rows), "fina_indicator": fina}


def _sample_event_dict() -> dict:
    return {
        "version": "SignalEventV1",
        "event_date": "2026-05-01",
        "event_id": "evt_20260501_001",
        "event_type": "earnings_surprise",
        "severity": "high",
        "summary": "300004.SZ netprofit_yoy 200% is a significant outlier.",
        "affected_sectors": ["创业板"],
        "affected_symbols": ["300004.SZ"],
        "source_refs": ["fina_indicator.netprofit_yoy"],
        "confidence": 0.85,
        "recommended_next_action": "检查持仓集中度",
    }


@pytest.fixture()
def mock_llm() -> LLMClient:
    with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response("[]")
        yield LLMClient(api_key="test-key")


class TestScanEvents:
    def test_valid_json_returns_events(self, mock_llm: LLMClient) -> None:
        mock_llm._client.messages.create.return_value = _make_response(
            json.dumps([_sample_event_dict()])
        )
        result = scan_events(_make_data(), "20260501", mock_llm)

        assert len(result) == 1
        assert isinstance(result[0], SignalEventV1)
        assert result[0].event_id == "evt_20260501_001"
        assert result[0].event_type == "earnings_surprise"
        assert result[0].confidence == 0.85

    def test_empty_array_returns_empty_list(self, mock_llm: LLMClient) -> None:
        mock_llm._client.messages.create.return_value = _make_response("[]")
        result = scan_events(_make_data(), "20260501", mock_llm)

        assert result == []

    def test_malformed_json_retries_then_raises(self, mock_llm: LLMClient) -> None:
        mock_llm._client.messages.create.return_value = _make_response("not json")
        with pytest.raises(ValueError):
            scan_events(_make_data(), "20260501", mock_llm)

    def test_event_type_is_valid(self, mock_llm: LLMClient) -> None:
        events = [_sample_event_dict() for _ in range(3)]
        mock_llm._client.messages.create.return_value = _make_response(
            json.dumps(events)
        )
        result = scan_events(_make_data(), "20260501", mock_llm)

        allowed = {
            "policy_event", "earnings_surprise", "factor_drift",
            "sector_rotation", "northbound_flow", "sentiment_shift",
            "analyst_revision", "other",
        }
        for event in result:
            assert event.event_type in allowed
