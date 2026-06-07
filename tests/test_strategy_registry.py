"""Tests for strategy registry governance helpers."""

from __future__ import annotations

from pathlib import Path

from src.strategies.registry import (
    load_strategy_registry,
    production_strategy_paths,
    registry_strategy_paths,
)


def test_registry_loads_scoped_strategy_entries(tmp_path):
    registry_path = tmp_path / "strategies" / "registry.yaml"
    registry_path.parent.mkdir()
    registry_path.write_text(
        "version: StrategyRegistryV1\n"
        "strategies:\n"
        "  prod:\n"
        "    path: strategies/prod/config.yaml\n"
        "    scope: production\n"
        "    lifecycle: paper\n"
        "    source: manual\n"
        "  draft:\n"
        "    path: strategies/draft/config.yaml\n"
        "    scope: research\n"
        "    lifecycle: draft\n"
        "    source: llm\n",
        encoding="utf-8",
    )

    registry = load_strategy_registry(registry_path)

    assert registry is not None
    assert registry_strategy_paths(registry, scope="production") == [
        "strategies/prod/config.yaml"
    ]
    assert registry_strategy_paths(registry, scope="research") == [
        "strategies/draft/config.yaml"
    ]


def test_production_strategy_paths_falls_back_without_registry(tmp_path):
    assert production_strategy_paths(["legacy.yaml"], base_dir=tmp_path) == ["legacy.yaml"]
