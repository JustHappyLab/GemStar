"""gemstar cleanup — remove failed or stale run artifacts and DB records."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import typer

from src.cli.app import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit

_DEFAULT_CLEAN_STATUSES = ("failed", "manual_attention")


def cleanup_cmd(
    status: str = typer.Option(
        None, "--status", "-s",
        help="Comma-separated statuses to clean (default: failed,manual_attention).",
    ),
    keep: int = typer.Option(
        0, "--keep", "-k",
        help="Keep the N most recent runs regardless of status.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n",
        help="Show what would be deleted without actually deleting.",
    ),
) -> None:
    """Remove failed or stale run artifacts and DB records."""
    config = load_config()
    db_path = config.db_path
    artifacts_dir = config.artifacts_dir

    if not Path(db_path).exists():
        console.print("[red]No state.db found. Run 'gemstar init' first.[/red]")
        raise typer.Exit(1)

    clean_statuses = (
        tuple(s.strip() for s in status.split(","))
        if status
        else _DEFAULT_CLEAN_STATUSES
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Find runs matching target statuses, excluding the N most recent
    all_runs = conn.execute(
        "SELECT run_id, status, started_at FROM runs ORDER BY started_at DESC"
    ).fetchall()

    targets = []
    for i, row in enumerate(all_runs):
        if keep and i < keep:
            continue
        if row["status"] in clean_statuses:
            targets.append(row)

    if not targets:
        console.print("[green]Nothing to clean.[/green]")
        conn.close()
        return

    fmt = get_output_format()
    rows = []
    for row in targets:
        art_path = Path(artifacts_dir, row["run_id"])
        has_artifacts = art_path.exists()
        rows.append({
            "run_id": row["run_id"],
            "status": row["status"],
            "started": row["started_at"] or "",
            "artifacts": "yes" if has_artifacts else "no",
        })

    if fmt == "json":
        emit(rows, format="json")
    else:
        emit(rows, format="table", title="Runs to clean")

    if dry_run:
        console.print(f"\n[yellow]Dry run — {len(targets)} run(s) would be cleaned.[/yellow]")
        conn.close()
        return

    deleted_artifacts = 0
    deleted_records = 0
    for row in targets:
        run_id = row["run_id"]
        art_path = Path(artifacts_dir, run_id)
        if art_path.exists():
            shutil.rmtree(art_path)
            deleted_artifacts += 1
        conn.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        deleted_records += 1

    conn.commit()
    conn.close()

    console.print(
        f"\n[green]Cleaned {deleted_records} run(s), "
        f"removed {deleted_artifacts} artifact dir(s).[/green]"
    )
