"""gemstar reset — reset paper-trading and run state with backups."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

import typer

from src.cli.config import find_config, load_config
from src.cli.output import console

ResetTarget = Literal["trade", "all"]


def reset_cmd(
    target: ResetTarget = typer.Argument(
        "trade",
        help="Reset target: trade resets paper account; all also clears run records/artifacts.",
    ),
    include_alerts: bool = typer.Option(
        False,
        "--include-alerts",
        help="Also clear alerts/live.jsonl notification history.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be reset without changing files.",
    ),
    keep: int = typer.Option(
        0,
        "--keep",
        "-k",
        help="For reset all, keep the N most recent runs.",
    ),
    backup_dir: str = typer.Option(
        "reset-backups",
        "--backup-dir",
        help="Directory for reset backups.",
    ),
) -> None:
    """Reset GemStar local state safely."""
    config_path = _resolve_config_path()
    if config_path is not None:
        os.chdir(config_path.parent)
    config = load_config(config_path)

    if target == "all":
        include_alerts = True if not include_alerts else include_alerts
    if keep < 0:
        raise typer.BadParameter("keep must be non-negative")

    backup_root = Path(backup_dir) / datetime.now().strftime("%Y%m%d-%H%M%S")
    plan = _build_plan(
        target=target,
        include_alerts=include_alerts,
        config=config,
        backup_root=backup_root,
        keep=keep,
    )
    _print_plan(plan, dry_run=dry_run)

    if dry_run:
        return
    if not yes:
        confirmed = typer.confirm("Proceed with reset?", default=False)
        if not confirmed:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    _apply_plan(plan)
    console.print(f"[green]Reset complete.[/green] backup={backup_root}")


def _resolve_config_path() -> Path | None:
    found = find_config()
    if found:
        return found.resolve()
    repo_root = Path(__file__).resolve().parents[3]
    for name in ("gemstar.yaml", "gemstar.yml", ".gemstar.yaml"):
        candidate = repo_root / name
        if candidate.exists():
            return candidate.resolve()
    return None


def _build_plan(
    *,
    target: ResetTarget,
    include_alerts: bool,
    config,
    backup_root: Path,
    keep: int,
) -> dict:
    backup_files = [
        Path("alerts/ledger.jsonl"),
        Path(config.artifacts_dir) / "current" / "trade_status.json",
        Path(config.artifacts_dir) / "current" / "trade_status.md",
    ]
    delete_files = list(backup_files)
    if include_alerts:
        alerts_path = Path("alerts/live.jsonl")
        backup_files.append(alerts_path)
        delete_files.append(alerts_path)

    plan = {
        "backup_root": backup_root,
        "backup_files": [p for p in backup_files if p.exists()],
        "delete_files": [p for p in delete_files if p.exists()],
        "run_artifacts": [],
        "run_ids": [],
        "state_db": Path(config.db_path),
    }
    if target == "all":
        db_path = Path(config.db_path)
        if db_path.exists():
            plan["backup_files"].append(db_path)
            run_ids = _run_ids_to_delete(db_path, keep=keep)
            plan["run_ids"] = run_ids
            artifacts_dir = Path(config.artifacts_dir)
            plan["run_artifacts"] = [
                artifacts_dir / run_id
                for run_id in run_ids
                if (artifacts_dir / run_id).exists()
            ]
    return plan


def _run_ids_to_delete(db_path: Path, keep: int) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id FROM runs ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()
    ids = [row[0] for row in rows]
    return ids[keep:] if keep else ids


def _print_plan(plan: dict, *, dry_run: bool) -> None:
    title = "Reset dry run" if dry_run else "Reset plan"
    console.print(f"[cyan]{title}[/cyan]")
    console.print(f"  backup: {plan['backup_root']}")
    for label, paths in (
        ("backup files", plan["backup_files"]),
        ("delete files", plan["delete_files"]),
        ("run artifact dirs", plan["run_artifacts"]),
    ):
        console.print(f"  {label}: {len(paths)}")
        for path in paths[:10]:
            console.print(f"    - {path}")
        if len(paths) > 10:
            console.print(f"    ... +{len(paths) - 10} more")
    if plan["run_ids"]:
        console.print(f"  run records: {len(plan['run_ids'])}")


def _apply_plan(plan: dict) -> None:
    backup_root: Path = plan["backup_root"]
    backup_root.mkdir(parents=True, exist_ok=True)
    for src in plan["backup_files"]:
        _backup_file(src, backup_root)
    for path in plan["delete_files"]:
        path.unlink(missing_ok=True)
    for path in plan["run_artifacts"]:
        shutil.rmtree(path, ignore_errors=True)
    if plan["run_ids"]:
        _delete_run_records(plan["state_db"], plan["run_ids"])


def _backup_file(src: Path, backup_root: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    dest = backup_root / src
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _delete_run_records(db_path: Path, run_ids: list[str]) -> None:
    if not db_path.exists() or not run_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        for run_id in run_ids:
            conn.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()
