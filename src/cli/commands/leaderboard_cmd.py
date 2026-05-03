"""gemstar leaderboard — show strategy rankings from the latest run."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import typer

from src.cli.app import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit


def leaderboard_cmd(
    run_id: str = typer.Option(None, "--run", "-r", help="Run ID (default: latest completed)."),
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

    if not entries:
        console.print(f"[yellow]Leaderboard empty for run {run_id}.[/yellow]")
        return

    fmt = get_output_format()
    if fmt == "json":
        emit(lb_data, format="json")
    else:
        rows = []
        for e in entries:
            rows.append({
                "rank": f"#{e['rank']}",
                "strategy": e["name"],
                "sharpe": f"{e['sharpe']:.2f}",
                "cagr": f"{e['cagr']:.2%}",
                "max_dd": f"{e['max_drawdown']:.2%}",
                "alpha": f"{e['alpha']:.2%}",
                "change": e.get("rank_change", ""),
            })
        emit(rows, format="table", title=f"Leaderboard ({run_id})")
