"""gemstar promote-strategy — move a research strategy into the registry."""

from __future__ import annotations

import shutil
import os
from pathlib import Path
from typing import Literal

import typer
import yaml

from src.cli.config import find_config
from src.cli.output import console
from src.schemas.strategy import StrategyConfigV1
from src.strategies.registry import (
    StrategyRegistryEntry,
    StrategyRegistryV1,
    load_strategy_registry,
    registry_path,
    save_strategy_registry,
)


def promote_strategy_cmd(
    run_id: str | None = typer.Option(
        None,
        "--run",
        "-r",
        help="Run ID containing artifacts/<run>/drafts/*.yaml.",
    ),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        "-s",
        help="Strategy name or draft filename stem to promote.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="Existing strategy YAML path to promote.",
    ),
    scope: Literal["production", "research"] = typer.Option(
        "production",
        "--scope",
        help="Registry scope for the promoted strategy.",
        hidden=True,
    ),
    lifecycle: Literal["draft", "candidate", "paper", "active", "retired", "rejected"] = typer.Option(
        "candidate",
        "--lifecycle",
        help="Initial lifecycle state in the registry.",
        hidden=True,
    ),
    source: Literal["manual", "llm", "promoted", "imported"] = typer.Option(
        "promoted",
        "--source",
        help="Source label stored in the registry.",
        hidden=True,
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Overwrite an existing target without prompting.",
    ),
) -> None:
    """Promote a draft or existing YAML into strategies/registry.yaml."""
    workspace = _workspace_root()
    os.chdir(workspace)
    source_path = _resolve_source_path(workspace, run_id=run_id, strategy=strategy, path=path)
    config = StrategyConfigV1.from_yaml(source_path)
    strategy_id = _safe_strategy_id(config.name)
    target_path = Path("strategies") / strategy_id / "config.yaml"

    if source_path.resolve() != target_path.resolve():
        if target_path.exists() and not yes:
            overwrite = typer.confirm(f"{target_path} already exists. Overwrite?", default=False)
            if not overwrite:
                console.print("[yellow]Aborted.[/yellow]")
                raise typer.Exit(0)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)

    reg_path = registry_path()
    registry = load_strategy_registry(reg_path) or StrategyRegistryV1()
    registry.strategies[strategy_id] = StrategyRegistryEntry(
        path=str(target_path),
        scope=scope,
        lifecycle=lifecycle,
        source=source,
        notes=f"Promoted from {source_path}",
    )
    save_strategy_registry(registry, reg_path)

    console.print(
        f"[green]Promoted[/green] {config.name} -> {target_path} "
        f"(scope={scope}, lifecycle={lifecycle})"
    )


def _workspace_root() -> Path:
    config = find_config()
    if config is not None:
        root = config.resolve().parent
        return root
    return Path.cwd()


def _resolve_source_path(
    workspace: Path,
    *,
    run_id: str | None,
    strategy: str | None,
    path: str | None,
) -> Path:
    if path:
        source = Path(path)
        if not source.is_absolute():
            source = workspace / source
        if not source.exists():
            raise typer.BadParameter(f"Strategy YAML not found: {source}")
        return source

    if not run_id or not strategy:
        raise typer.BadParameter("Provide either --path or both --run and --strategy.")

    drafts_dir = workspace / "artifacts" / run_id / "drafts"
    if not drafts_dir.exists():
        raise typer.BadParameter(f"Draft directory not found: {drafts_dir}")

    matches = []
    for candidate in sorted(drafts_dir.glob("*.yaml")):
        if candidate.stem == strategy:
            matches.append(candidate)
            continue
        try:
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if data.get("name") == strategy:
            matches.append(candidate)

    if not matches:
        raise typer.BadParameter(f"No draft strategy named {strategy!r} under {drafts_dir}")
    if len(matches) > 1:
        choices = ", ".join(str(p.name) for p in matches)
        raise typer.BadParameter(f"Multiple draft matches for {strategy!r}: {choices}")
    return matches[0]


def _safe_strategy_id(name: str) -> str:
    import re

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return safe or "promoted_strategy"
