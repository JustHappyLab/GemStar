"""Tests for src.research.analyst with an offline LLMGenerate fake."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.research.analyst import generate_tickets
from src.schemas.signal import MarketRegimeV1, SignalEventV1
from tests.llm_fakes import FakeLLM


# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

def _make_regime() -> MarketRegimeV1:
    return MarketRegimeV1(
        as_of_date=date(2026, 5, 3),
        regime="bullish",
        confidence=0.8,
        key_drivers=["成交量放大"],
        style_bias="成长",
    )


def _make_events() -> list[SignalEventV1]:
    return [
        SignalEventV1(
            event_date=date(2026, 5, 3),
            event_id="evt_001",
            event_type="earnings_surprise",
            severity="medium",
            summary="某公司利润超预期",
        )
    ]


def _make_pool_json(tmpdir: Path) -> Path:
    pool = {
        "version": 2,
        "last_updated": "2026-05-03",
        "active": [
            {"name": "roe", "source": "fina_indicator", "status": "active"},
            {"name": "momentum_20d", "source": "daily.close", "status": "active"},
        ],
        "watchlist": [],
        "retired": [],
        "candidates": [],
    }
    path = tmpdir / "pool.json"
    path.write_text(json.dumps(pool))
    return path


def _valid_ticket_json() -> str:
    return json.dumps([
        {
            "version": "ResearchTicketV1",
            "ticket_id": "ticket_20260503_001",
            "created_date": "2026-05-03",
            "ticket_type": "factor_tweak",
            "hypothesis": "将 momentum_20d 权重从 0.15 提升至 0.20",
            "rationale": "当前牛市环境，动量因子IC持续走高",
            "affected_factors": ["momentum_20d"],
            "affected_sectors": ["成长"],
            "confidence": 0.7,
            "source_regime": "bullish",
            "source_events": ["evt_001"],
            "status": "draft",
        }
    ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateTickets:

    def test_valid_tickets_returns_list(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)
        regime = _make_regime()
        events = _make_events()

        llm = FakeLLM(_valid_ticket_json())
        result = generate_tickets(regime, events, None, pool_path, llm)

        assert len(result) == 1
        ticket = result[0]
        assert ticket.ticket_id == "ticket_20260503_001"
        assert ticket.ticket_type == "factor_tweak"
        assert ticket.affected_factors == ["momentum_20d"]
        assert ticket.status == "draft"

    def test_empty_response_returns_empty_list(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        llm = FakeLLM("[]")
        result = generate_tickets(
            _make_regime(), _make_events(), None, pool_path, llm
        )

        assert result == []

    def test_trailing_llm_explanation_is_ignored(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        llm = FakeLLM(_valid_ticket_json() + "\n已根据上下文生成研究工单。")
        result = generate_tickets(
            _make_regime(), _make_events(), None, pool_path, llm
        )

        assert len(result) == 1
        assert result[0].ticket_id == "ticket_20260503_001"

    def test_unknown_factor_filtered_out(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        ticket_with_bad_factor = json.dumps([
            {
                "version": "ResearchTicketV1",
                "ticket_id": "ticket_bad",
                "created_date": "2026-05-03",
                "ticket_type": "new_factor",
                "hypothesis": "test",
                "rationale": "test",
                "affected_factors": ["nonexistent"],
                "confidence": 0.5,
                "status": "draft",
            }
        ])

        llm = FakeLLM(ticket_with_bad_factor)
        result = generate_tickets(
            _make_regime(), _make_events(), None, pool_path, llm
        )

        assert result == []

    def test_prompt_includes_factor_allow_list_and_event_ids(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)
        llm = FakeLLM("[]")

        result = generate_tickets(
            _make_regime(), _make_events(), None, pool_path, llm
        )

        assert result == []
        prompt = llm.calls[0]["prompt"]
        assert "可引用因子池" in prompt
        assert "roe" in prompt
        assert "momentum_20d" in prompt
        assert "id=evt_001" in prompt

    def test_malformed_json_retries_then_raises(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        llm = FakeLLM("not valid json")

        with pytest.raises(ValueError):
            generate_tickets(
                _make_regime(), _make_events(), None, pool_path, llm
            )
