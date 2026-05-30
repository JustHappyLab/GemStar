"""gemstar status — show run status."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import typer

from src.cli.output import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit


def status_cmd(
    run_id: str = typer.Argument(None, help="Run ID. Default: latest."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Show the status of a pipeline run."""
    fmt = get_output_format()
    config = load_config(Path(config_path) if config_path else None)
    db_path = config.db_path

    if not Path(db_path).exists():
        console.print("[red]No state.db found. Run 'gemstar init' first.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if run_id is None:
        row = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            console.print("[yellow]No runs found.[/yellow]")
            conn.close()
            raise typer.Exit(0)
        run_id = row["run_id"]
    else:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            console.print(f"[red]Run not found:[/red] {run_id}")
            conn.close()
            raise typer.Exit(1)

    steps = conn.execute(
        "SELECT step_id, role, status, latency_sec, error FROM steps WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()

    conn.close()

    if fmt == "json":
        emit({
            "run_id": run_id,
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "steps": [dict(s) for s in steps],
        }, format="json")
    else:
        status_color = "green" if row["status"] == "completed" else "red"
        console.print(f"[bold]Run:[/bold] {run_id}")
        console.print(f"[bold]Status:[/bold] [{status_color}]{row['status']}[/]")
        console.print(f"[bold]Started:[/bold] {row['started_at']}")
        if row["finished_at"]:
            console.print(f"[bold]Finished:[/bold] {row['finished_at']}")

        if steps:
            console.print("\n[bold]Steps:[/bold]")
            for s in steps:
                icon = {"completed": "[green]ok[/]", "failed": "[red]FAIL[/]"}.get(s["status"], "[dim]...[/]")
                latency = f" ({s['latency_sec']:.1f}s)" if s["latency_sec"] else ""
                console.print(f"  {icon} {s['step_id']}{latency}")
                if s["error"]:
                    console.print(f"      [red]{s['error']}[/red]")
