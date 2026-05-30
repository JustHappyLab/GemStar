"""gemstar history — list past runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import typer

from src.cli.output import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit


def history_cmd(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of runs to show."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """List recent pipeline runs."""
    fmt = get_output_format()
    config = load_config(Path(config_path) if config_path else None)
    db_path = config.db_path

    if not Path(db_path).exists():
        console.print("[red]No state.db found. Run 'gemstar init' first.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT run_id, status, started_at, finished_at FROM runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No runs found.[/yellow]")
        return

    if fmt == "json":
        emit([dict(r) for r in rows], format="json")
    else:
        table_data = []
        for r in rows:
            table_data.append({
                "run_id": r["run_id"],
                "status": r["status"],
                "started": r["started_at"] or "",
                "finished": r["finished_at"] or "",
            })
        emit(table_data, format="table", title="Recent Runs")
