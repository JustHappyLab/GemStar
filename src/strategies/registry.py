"""Strategy registry for production/research governance."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


StrategyScope = Literal["production", "research"]
StrategyLifecycle = Literal["draft", "candidate", "paper", "active", "retired", "rejected"]
StrategySource = Literal["manual", "llm", "promoted", "imported"]


class StrategyRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    scope: StrategyScope = "research"
    lifecycle: StrategyLifecycle = "draft"
    source: StrategySource = "manual"
    notes: str = ""


class StrategyRegistryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["StrategyRegistryV1"] = "StrategyRegistryV1"
    strategies: dict[str, StrategyRegistryEntry] = Field(default_factory=dict)


def registry_path(base_dir: str | Path = ".") -> Path:
    return Path(base_dir) / "strategies" / "registry.yaml"


def load_strategy_registry(path: str | Path = "strategies/registry.yaml") -> StrategyRegistryV1 | None:
    p = Path(path)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return StrategyRegistryV1.model_validate(data)


def save_strategy_registry(
    registry: StrategyRegistryV1,
    path: str | Path = "strategies/registry.yaml",
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = registry.model_dump(mode="json")
    p.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def registry_strategy_paths(
    registry: StrategyRegistryV1 | None,
    *,
    scope: StrategyScope | Literal["all"] = "production",
    lifecycle: StrategyLifecycle | Literal["all"] = "all",
) -> list[str]:
    if registry is None:
        return []
    paths: list[str] = []
    for entry in registry.strategies.values():
        if scope != "all" and entry.scope != scope:
            continue
        if lifecycle != "all" and entry.lifecycle != lifecycle:
            continue
        paths.append(entry.path)
    return paths


def production_strategy_paths(
    fallback: list[str] | None = None,
    *,
    base_dir: str | Path = ".",
) -> list[str]:
    registry = load_strategy_registry(registry_path(base_dir))
    paths = registry_strategy_paths(registry, scope="production", lifecycle="all")
    return paths or list(fallback or [])
