"""Tests for ReviewNotesV1 schema — round-trip JSON serialization."""

from src.schemas.review import ReviewNotesV1


def test_review_notes_roundtrip():
    """ReviewNotesV1 survives JSON round-trip."""
    notes = ReviewNotesV1(
        strategy_id="chinext_lstm_mf8",
        run_id="run_001",
        verdict_summary="candidate — 全部硬门通过",
        explanation="该策略在所有5项硬门检查中均通过。Sharpe 1.35超过1.0阈值，Calmar 1.10超过0.8阈值。",
        risk_highlights=[
            "max_drawdown -22.3% 接近 -30% 阈值",
            "分段Sharpe标准差0.38，接近0.5上限",
        ],
        confidence=0.85,
    )

    json_str = notes.model_dump_json()
    restored = ReviewNotesV1.model_validate_json(json_str)

    assert restored.strategy_id == notes.strategy_id
    assert restored.run_id == notes.run_id
    assert restored.verdict_summary == notes.verdict_summary
    assert restored.explanation == notes.explanation
    assert restored.risk_highlights == notes.risk_highlights
    assert restored.confidence == notes.confidence


def test_review_notes_defaults():
    """ReviewNotesV1 has sensible defaults."""
    notes = ReviewNotesV1(strategy_id="test")
    assert notes.version == "ReviewNotesV1"
    assert notes.run_id == ""
    assert notes.verdict_summary == ""
    assert notes.explanation == ""
    assert notes.risk_highlights == []
    assert notes.confidence == 0.5


def test_review_notes_confidence_bounds():
    """Confidence must be between 0 and 1."""
    ReviewNotesV1(strategy_id="t", confidence=0.0)
    ReviewNotesV1(strategy_id="t", confidence=1.0)

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReviewNotesV1(strategy_id="t", confidence=-0.1)

    with pytest.raises(ValidationError):
        ReviewNotesV1(strategy_id="t", confidence=1.1)
