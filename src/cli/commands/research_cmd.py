"""gemstar research — explicit LLM-assisted exploration entrypoint."""

from __future__ import annotations

import typer

from src.cli.commands.run_cmd import execute_run


def research_cmd(
    date: str = typer.Option(None, "--date", "-d", help="Research date (YYYYMMDD). Default: today."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Run the research pipeline with LLM exploration enabled."""
    execute_run(
        date=date,
        config_path=config_path,
        llm_available=True,
    )
