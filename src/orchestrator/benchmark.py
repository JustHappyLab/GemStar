"""Benchmark resolution for run-level reporting and backtests."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.orchestrator.universe import UniverseResolution, resolve_strategy_universe
from src.schemas.strategy import StrategyConfigV1


@dataclass(frozen=True)
class BenchmarkResolution:
    requested: str
    resolved: str
    name: str
    reason: str
    candidates: tuple[str, ...]

    def model_dump(self) -> dict:
        return asdict(self)


_BENCHMARK_BY_BASE = {
    "a_share": ("000985.CSI", "CSI All Share", ("000985.CSI", "000300.SH")),
    "chinext": ("399006.SZ", "ChiNext Index", ("399006.SZ",)),
    "star": ("000688.SH", "STAR 50 Index", ("000688.SH", "000985.CSI", "000300.SH")),
    "main_board": ("000300.SH", "CSI 300 Index", ("000300.SH", "000985.CSI")),
}


def resolve_benchmark_for_strategies(
    requested_benchmark: str,
    strategies: list[StrategyConfigV1],
) -> BenchmarkResolution:
    universes = [resolve_strategy_universe(strategy) for strategy in strategies]
    return resolve_benchmark_for_universes(requested_benchmark, universes)


def resolve_benchmark_for_universes(
    requested_benchmark: str | None,
    universes: list[UniverseResolution],
) -> BenchmarkResolution:
    requested = (requested_benchmark or "auto").strip()
    if requested.lower() != "auto":
        return BenchmarkResolution(
            requested=requested,
            resolved=requested,
            name="Explicit benchmark",
            reason="Config explicitly requested this benchmark.",
            candidates=(requested,),
        )

    bases = {_base_universe(u.resolved) for u in universes}
    if len(bases) == 1:
        base = next(iter(bases))
        code, name, candidates = _BENCHMARK_BY_BASE.get(base, _BENCHMARK_BY_BASE["a_share"])
        return BenchmarkResolution(
            requested="auto",
            resolved=code,
            name=name,
            reason=f"Auto-selected to match resolved universe base: {base}.",
            candidates=candidates,
        )

    code, name, candidates = _BENCHMARK_BY_BASE["a_share"]
    mixed = ", ".join(sorted(bases)) if bases else "none"
    return BenchmarkResolution(
        requested="auto",
        resolved=code,
        name=name,
        reason=f"Auto-selected broad A-share benchmark because strategies use mixed universe bases: {mixed}.",
        candidates=candidates,
    )


def describe_benchmark_resolution(resolution: BenchmarkResolution | dict | None) -> str:
    if resolution is None:
        return ""
    if isinstance(resolution, dict):
        requested = str(resolution.get("requested", ""))
        resolved = str(resolution.get("resolved", ""))
        name = str(resolution.get("name", ""))
        reason = str(resolution.get("reason", ""))
    else:
        requested = resolution.requested
        resolved = resolution.resolved
        name = resolution.name
        reason = resolution.reason
    return f"{resolved} ({name}, requested: {requested}) - {reason}"


def _base_universe(universe: str) -> str:
    if universe.startswith("chinext"):
        return "chinext"
    if universe.startswith("star"):
        return "star"
    if universe.startswith("main_board"):
        return "main_board"
    return "a_share"
