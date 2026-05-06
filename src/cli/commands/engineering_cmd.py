"""gemstar engineering — inspect and execute bounded engineering tasks."""

from __future__ import annotations

from pathlib import Path

import typer

from src.cli.app import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit
from src.engineering.executor import execute_engineering_task


def engineering_run_cmd(
    task_path: Path = typer.Argument(..., help="Path to engineering_task_*.json."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Render prompt without running the agent."),
    allow_dirty: bool = typer.Option(False, "--allow-dirty", help="Allow execution with a dirty git worktree."),
) -> None:
    """Execute one engineering task, then validate changed paths."""
    config = load_config(Path(config_path) if config_path else None)
    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        repo_root=Path.cwd(),
        allow_dirty=allow_dirty,
        dry_run=dry_run,
    )

    fmt = get_output_format()
    if fmt == "json":
        emit(result.model_dump(), format="json")
    else:
        emit(_summary(result), format="table", title="Engineering Execution")
        if result.status == "dry_run":
            console.print("\n[bold]Prompt[/bold]\n")
            console.print(result.prompt)

    if result.status in {"failed", "rejected"}:
        raise typer.Exit(1)


def _summary(result) -> dict:
    return {
        "task_id": result.task_id,
        "run_id": result.run_id,
        "role": result.role,
        "status": result.status,
        "provider": result.provider,
        "changed_paths": ", ".join(result.changed_paths),
        "violations": len(result.violations),
        "error": result.error_message,
    }
