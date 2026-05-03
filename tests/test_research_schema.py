"""Tests for ResearchTicketV1 schema — round-trip JSON serialization."""

from datetime import date

from src.schemas.research import ResearchTicketV1


def test_research_ticket_roundtrip():
    """ResearchTicketV1 survives JSON round-trip."""
    ticket = ResearchTicketV1(
        ticket_id="ticket_20260503_001",
        created_date=date(2026, 5, 3),
        ticket_type="weight_rebalance",
        hypothesis="将 momentum_20d 权重从 0.15 提升至 0.20",
        rationale="当前牛市环境，动量因子IC持续走高",
        affected_factors=["momentum_20d", "roe"],
        affected_sectors=["科技"],
        confidence=0.75,
        source_regime="bullish",
        source_events=["evt_20260503_001"],
        status="draft",
    )

    json_str = ticket.model_dump_json()
    restored = ResearchTicketV1.model_validate_json(json_str)

    assert restored.ticket_id == ticket.ticket_id
    assert restored.created_date == ticket.created_date
    assert restored.ticket_type == ticket.ticket_type
    assert restored.hypothesis == ticket.hypothesis
    assert restored.affected_factors == ticket.affected_factors
    assert restored.confidence == ticket.confidence
    assert restored.source_regime == ticket.source_regime
    assert restored.status == ticket.status


def test_research_ticket_defaults():
    """ResearchTicketV1 has sensible defaults for optional fields."""
    ticket = ResearchTicketV1(
        ticket_id="t1",
        created_date=date(2026, 5, 3),
        ticket_type="new_factor",
        hypothesis="test",
        rationale="test",
    )

    assert ticket.version == "ResearchTicketV1"
    assert ticket.affected_factors == []
    assert ticket.affected_sectors == []
    assert ticket.confidence == 0.5
    assert ticket.source_regime is None
    assert ticket.source_events == []
    assert ticket.status == "draft"


def test_research_ticket_confidence_bounds():
    """Confidence must be between 0 and 1."""
    ResearchTicketV1(
        ticket_id="t1",
        created_date=date(2026, 5, 3),
        ticket_type="new_strategy",
        hypothesis="test",
        rationale="test",
        confidence=0.0,
    )

    ResearchTicketV1(
        ticket_id="t2",
        created_date=date(2026, 5, 3),
        ticket_type="new_strategy",
        hypothesis="test",
        rationale="test",
        confidence=1.0,
    )

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResearchTicketV1(
            ticket_id="t3",
            created_date=date(2026, 5, 3),
            ticket_type="new_strategy",
            hypothesis="test",
            rationale="test",
            confidence=1.5,
        )


def test_research_ticket_type_enum():
    """ticket_type must be one of the 4 allowed values."""
    for tt in ("new_factor", "factor_tweak", "new_strategy", "weight_rebalance"):
        ticket = ResearchTicketV1(
            ticket_id="t1",
            created_date=date(2026, 5, 3),
            ticket_type=tt,
            hypothesis="test",
            rationale="test",
        )
        assert ticket.ticket_type == tt


def test_research_ticket_status_enum():
    """status must be one of the 4 allowed values."""
    for s in ("draft", "validated", "approved", "rejected"):
        ticket = ResearchTicketV1(
            ticket_id="t1",
            created_date=date(2026, 5, 3),
            ticket_type="new_factor",
            hypothesis="test",
            rationale="test",
            status=s,
        )
        assert ticket.status == s
