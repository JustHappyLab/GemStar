"""gemstar leaderboard — show strategy rankings from the latest run."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

import typer

from src.cli.output import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit
from src.strategies.registry import load_strategy_registry


def leaderboard_cmd(
    run_id: str = typer.Option(None, "--run", "-r", help="Run ID (default: latest completed)."),
    scope: Literal["all", "production", "research"] = typer.Option(
        "production",
        "--scope",
        help="Strategy scope to show: all, production, or research.",
    ),
    status: Literal["all", "candidate", "paper", "active", "rejected"] = typer.Option(
        "all",
        "--status",
        help="Filter by leaderboard status.",
        hidden=True,
    ),
) -> None:
    """Show strategy leaderboard from a pipeline run."""
    config = load_config()
    db_path = config.db_path
    artifacts_dir = config.artifacts_dir

    if not Path(db_path).exists():
        console.print("[red]No state.db found. Run 'gemstar init' first.[/red]")
        raise typer.Exit(1)

    # Find run_id
    if run_id is None:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            console.print("[yellow]No completed runs found.[/yellow]")
            raise typer.Exit(0)
        run_id = row[0]

    # Read leaderboard artifact
    lb_path = Path(artifacts_dir, run_id, "leaderboard.json")
    if not lb_path.exists():
        console.print(f"[red]No leaderboard found for run {run_id}.[/red]")
        raise typer.Exit(1)

    lb_data = json.loads(lb_path.read_text())
    entries = lb_data.get("entries", [])
    total_entries = len(entries)
    meta = _leaderboard_meta(entries, run_id=run_id, scope=scope, status=status)
    entries = _filter_entries(entries, scope=scope, status=status)
    meta["shown"] = len(entries)

    if not entries:
        console.print(
            f"[yellow]Leaderboard empty for run {run_id} "
            f"(scope={scope}, status={status}, total={total_entries}, "
            f"production={meta['production_in_run']}/{meta['production_registered']}).[/yellow]"
        )
        return

    fmt = get_output_format()
    if fmt == "json":
        emit(
            {
                **lb_data,
                "entries": entries,
                "meta": {
                    **meta,
                    "total": total_entries,
                },
            },
            format="json",
        )
    else:
        rows = []
        for e in entries:
            rows.append({
                "rank": f"#{e['rank']}",
                "strategy": e["name"],
                "status": e.get("status", "candidate"),
                "sharpe": f"{e['sharpe']:.2f}",
                "cagr": f"{e['cagr']:.2%}",
                "max_dd": f"{e['max_drawdown']:.2%}",
                "alpha": f"{e['alpha']:.2%}",
                "change": e.get("rank_change", ""),
            })
        title = (
            f"Leaderboard ({run_id}, scope={scope}, status={status}, "
            f"{len(entries)}/{total_entries}, production={meta['production_in_run']}/"
            f"{meta['production_registered']})"
        )
        emit(rows, format="table", title=title)


def _leaderboard_meta(
    entries: list[dict],
    *,
    run_id: str,
    scope: str,
    status: str,
) -> dict:
    production = _production_names()
    entry_names = {str(e.get("name", "")) for e in entries}
    production_in_run = sorted(production & entry_names)
    production_missing = sorted(production - entry_names)
    return {
        "run_id": run_id,
        "scope": scope,
        "status": status,
        "shown": 0,
        "production_registered": len(production),
        "production_in_run": len(production_in_run),
        "production_missing": production_missing,
    }


def _filter_entries(
    entries: list[dict],
    *,
    scope: str = "all",
    status: str = "all",
) -> list[dict]:
    filtered = list(entries)
    if status != "all":
        filtered = [e for e in filtered if e.get("status") == status]
    if scope == "all":
        return filtered

    production = _production_names()
    if scope == "production":
        return [e for e in filtered if e.get("name") in production]
    if scope == "research":
        return [e for e in filtered if e.get("name") not in production]
    return filtered


def _production_names() -> set[str]:
    from src.schemas.strategy import StrategyConfigV1

    registry = load_strategy_registry()
    if registry is None:
        return set()
    names: set[str] = set()
    for entry in registry.strategies.values():
        if entry.scope != "production":
            continue
        try:
            names.add(StrategyConfigV1.from_yaml(entry.path).name)
        except Exception:
            names.add(Path(entry.path).stem)
    return names
