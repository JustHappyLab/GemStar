"""Tests for deterministic research ticket generation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.research.analyst import generate_tickets
from src.schemas.factor import FactorHealthEntry, FactorHealthReportV1
from src.schemas.signal import MarketRegimeV1, SignalEventV1
from tests.llm_fakes import FakeLLM


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
            summary="300001.SZ netprofit_yoy is an earnings outlier.",
            source_refs=["fina_indicator.netprofit_yoy"],
            confidence=0.72,
        ),
        SignalEventV1(
            event_date=date(2026, 5, 3),
            event_id="evt_002",
            event_type="sentiment_shift",
            severity="high",
            summary="300002.SZ trades above 3x prior 20-day volume.",
            source_refs=["daily.vol"],
            confidence=0.84,
        ),
        SignalEventV1(
            event_date=date(2026, 5, 3),
            event_id="evt_003",
            event_type="factor_drift",
            severity="high",
            summary="300003.SZ shows abnormal 5-day momentum.",
            source_refs=["daily.close"],
            confidence=0.81,
        ),
    ]


def _make_pool_json(tmpdir: Path, names: list[str] | None = None) -> Path:
    names = names or [
        "roe",
        "momentum_20d",
        "moneyflow_surge_v1",
        "volume_price_corr_v1",
    ]
    pool = {
        "version": 2,
        "last_updated": "2026-05-03",
        "active": [
            {"name": name, "source": "test", "status": "active"}
            for name in names
        ],
        "watchlist": [],
        "retired": [],
        "candidates": [],
    }
    path = tmpdir / "pool.json"
    path.write_text(json.dumps(pool))
    return path


def _make_factor_health() -> FactorHealthReportV1:
    return FactorHealthReportV1(
        run_id="run_001",
        as_of_date=date(2026, 5, 3),
        entries=[
            FactorHealthEntry(
                factor_name="momentum_20d",
                ic_mean=-0.02,
                ic_ir=-0.5,
                coverage=0.95,
                status="critical",
            ),
            FactorHealthEntry(
                factor_name="roe",
                ic_mean=0.01,
                ic_ir=0.2,
                coverage=0.9,
                status="healthy",
            ),
        ],
    )


class TestGenerateTickets:
    def test_generates_tickets_without_llm(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)
        llm = FakeLLM("not json")

        result = generate_tickets(_make_regime(), _make_events(), None, pool_path, llm)

        assert llm.calls == []
        assert result
        assert [ticket.ticket_id for ticket in result] == [
            f"ticket_20260503_{index:03d}" for index in range(1, len(result) + 1)
        ]

    def test_event_types_map_to_ticket_types(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        result = generate_tickets(_make_regime(), _make_events(), None, pool_path, FakeLLM("ignored"))

        ticket_types = {ticket.ticket_type for ticket in result}
        assert "factor_tweak" in ticket_types
        assert "new_strategy" in ticket_types
        assert "weight_rebalance" in ticket_types

    def test_only_registered_factors_are_referenced(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path, names=["momentum_20d"])

        result = generate_tickets(_make_regime(), _make_events(), None, pool_path, FakeLLM("ignored"))

        assert result
        for ticket in result:
            assert set(ticket.affected_factors) <= {"momentum_20d"}

    def test_factor_health_creates_quarantine_ticket(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        result = generate_tickets(
            _make_regime(),
            [],
            _make_factor_health(),
            pool_path,
            FakeLLM("ignored"),
        )

        assert len(result) == 1
        assert result[0].ticket_type == "factor_tweak"
        assert result[0].affected_factors == ["momentum_20d"]
        assert "critical" in result[0].rationale

    def test_no_events_or_health_returns_empty_list(self, tmp_path: Path) -> None:
        pool_path = _make_pool_json(tmp_path)

        result = generate_tickets(_make_regime(), [], None, pool_path, FakeLLM("ignored"))

        assert result == []
