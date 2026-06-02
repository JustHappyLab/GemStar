"""Tests for deterministic event scanning."""

from __future__ import annotations

import pandas as pd

from src.schemas.signal import SignalEventV1
from src.scanner.event_scanner import scan_events
from tests.llm_fakes import FakeLLM


def _make_signal_data() -> dict[str, pd.DataFrame]:
    codes = [f"300{i:03d}.SZ" for i in range(21)]
    dates = pd.bdate_range("2026-03-01", periods=45).strftime("%Y%m%d").tolist()
    daily_rows = []
    for code_index, code in enumerate(codes):
        for date_index, trade_date in enumerate(dates):
            close = 10.0 + date_index * 0.01
            vol = 1_000_000.0
            if code_index == 1 and date_index == len(dates) - 1:
                vol = 6_000_000.0
            if code_index == 2 and date_index >= len(dates) - 5:
                close = 10.0 + (date_index - len(dates) + 6) * 1.0
            daily_rows.append(
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "pre_close": close,
                    "vol": vol,
                }
            )

    fina = pd.DataFrame(
        {
            "ts_code": codes,
            "ann_date": ["20260501"] * len(codes),
            "netprofit_yoy": [10.0] * 20 + [800.0],
        }
    )
    return {"daily": pd.DataFrame(daily_rows), "fina_indicator": fina}


class TestScanEvents:
    def test_generates_structured_events_without_llm(self) -> None:
        mock_llm = FakeLLM("not json")
        result = scan_events(_make_signal_data(), "20260501", mock_llm)

        assert mock_llm.calls == []
        assert all(isinstance(event, SignalEventV1) for event in result)
        assert [event.event_id for event in result] == [
            f"evt_20260501_{index:03d}" for index in range(1, len(result) + 1)
        ]

    def test_detects_earnings_volume_and_momentum_events(self) -> None:
        result = scan_events(_make_signal_data(), "20260501", FakeLLM("ignored"))

        event_types = {event.event_type for event in result}
        assert "earnings_surprise" in event_types
        assert "sentiment_shift" in event_types
        assert "factor_drift" in event_types

    def test_events_include_valid_contract_fields(self) -> None:
        result = scan_events(_make_signal_data(), "20260501", FakeLLM("ignored"))

        allowed = {
            "policy_event",
            "earnings_surprise",
            "factor_drift",
            "sector_rotation",
            "northbound_flow",
            "sentiment_shift",
            "analyst_revision",
            "other",
        }
        for event in result:
            assert event.event_type in allowed
            assert event.event_date.isoformat() == "2026-05-01"
            assert event.summary
            assert event.source_refs
            assert 0.0 <= event.confidence <= 1.0

    def test_no_signal_data_returns_empty_list(self) -> None:
        result = scan_events({"daily": pd.DataFrame(), "fina_indicator": pd.DataFrame()}, "20260501", FakeLLM("ignored"))

        assert result == []

    def test_earnings_detector_uses_latest_row_per_symbol(self) -> None:
        data = _make_signal_data()
        older_rows = data["fina_indicator"].assign(ann_date="20260401", netprofit_yoy=5.0)
        data["fina_indicator"] = pd.concat([older_rows, data["fina_indicator"]], ignore_index=True)

        result = scan_events(data, "20260501", FakeLLM("ignored"))
        earnings = [event for event in result if event.event_type == "earnings_surprise"][0]

        assert "1 stocks show earnings outliers" in earnings.summary
