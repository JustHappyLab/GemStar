from src.orchestrator.benchmark import (
    describe_benchmark_resolution,
    resolve_benchmark_for_strategies,
    resolve_benchmark_for_universes,
)
from src.orchestrator.universe import resolve_universe_value
from src.schemas.strategy import StrategyConfigV1


def test_explicit_benchmark_is_preserved():
    resolution = resolve_benchmark_for_universes("000300.SH", [])

    assert resolution.requested == "000300.SH"
    assert resolution.resolved == "000300.SH"
    assert resolution.candidates == ("000300.SH",)


def test_auto_chinext_uses_chinext_index():
    universe = resolve_universe_value("chinext_core")

    resolution = resolve_benchmark_for_universes("auto", [universe])

    assert resolution.resolved == "399006.SZ"
    assert resolution.name == "ChiNext Index"


def test_auto_general_strategy_uses_broad_a_share_benchmark():
    strategy = StrategyConfigV1(name="quality_value")

    resolution = resolve_benchmark_for_strategies("auto", [strategy])

    assert resolution.resolved == "000985.CSI"
    assert resolution.candidates[0] == "000985.CSI"
    assert "a_share" in resolution.reason


def test_auto_mixed_universes_uses_broad_a_share_benchmark():
    universes = [resolve_universe_value("chinext_core"), resolve_universe_value("star_core")]

    resolution = resolve_benchmark_for_universes("auto", universes)

    assert resolution.resolved == "000985.CSI"
    assert "mixed universe" in resolution.reason


def test_describe_benchmark_resolution_mentions_code_and_reason():
    resolution = resolve_benchmark_for_universes("auto", [resolve_universe_value("chinext_core")])

    description = describe_benchmark_resolution(resolution)

    assert "399006.SZ" in description
    assert "Auto-selected" in description
