"""gemstar init — create config template + migrate state DB."""

from __future__ import annotations

from pathlib import Path

import typer

from src.cli.output import get_output_format
from src.cli.config import write_template
from src.cli.output import console, emit


def init_cmd(
    config_path: Path = typer.Option(
        Path("gemstar.yaml"), "--config", "-c", help="Config file path."
    ),
) -> None:
    """Initialize GemStar project: write config template and migrate state DB."""
    fmt = get_output_format()

    # 1. Write config template
    if config_path.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
    else:
        write_template(config_path)
        console.print(f"[green]Created config:[/green] {config_path}")

    # 2. Migrate state DB
    from src.orchestrator.state_db import connect, migrate

    conn = connect("state.db")
    migrate(conn)
    conn.close()
    console.print("[green]Migrated state DB:[/green] state.db")

    if fmt == "json":
        emit({"config": str(config_path), "db": "state.db", "status": "ok"}, format="json")
