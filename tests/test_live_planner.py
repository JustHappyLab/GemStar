"""Tests for live target planner."""

import pytest

from src.live.planner import plan_live_targets


def test_plan_live_targets_allocates_across_top_stocks():
    targets = plan_live_targets(
        top_stocks=["300750.SZ", "300059.SZ"],
        prices={"300750.SZ": 100.0, "300059.SZ": 50.0},
        total_capital=100_000.0,
        position_pct=1.0,
        reason="top ranked",
    )

    assert [t.ts_code for t in targets] == ["300750.SZ", "300059.SZ"]
    assert [t.target_shares for t in targets] == [500, 1000]
    assert [t.target_weight for t in targets] == [0.5, 0.5]
    assert all(t.reason == "top ranked" for t in targets)


def test_plan_live_targets_scales_by_position_pct():
    targets = plan_live_targets(
        top_stocks=["300750.SZ", "300059.SZ"],
        prices={"300750.SZ": 100.0, "300059.SZ": 50.0},
        total_capital=100_000.0,
        position_pct=0.5,
    )

    assert [t.target_shares for t in targets] == [200, 500]
    assert [t.target_weight for t in targets] == [0.2, 0.25]


def test_plan_live_targets_returns_empty_for_empty_or_zero_exposure():
    assert plan_live_targets([], {"300750.SZ": 100.0}, 100_000.0, 1.0) == []
    assert plan_live_targets(["300750.SZ"], {"300750.SZ": 100.0}, 100_000.0, 0.0) == []
    assert plan_live_targets(["300750.SZ"], {"300750.SZ": 100.0}, 0.0, 1.0) == []


def test_plan_live_targets_skips_missing_prices():
    targets = plan_live_targets(
        top_stocks=["300750.SZ", "300059.SZ"],
        prices={"300750.SZ": 100.0},
        total_capital=100_000.0,
        position_pct=1.0,
    )

    assert [t.ts_code for t in targets] == ["300750.SZ"]


def test_plan_live_targets_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        plan_live_targets(["300750.SZ"], {"300750.SZ": 100.0}, -1.0, 1.0)

    with pytest.raises(ValueError):
        plan_live_targets(["300750.SZ"], {"300750.SZ": 100.0}, 100_000.0, 1.5)
