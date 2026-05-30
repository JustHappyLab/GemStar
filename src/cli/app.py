"""GemStar CLI — multi-agent quantitative research platform."""

from __future__ import annotations

import typer

from src.cli.output import OutputFormat, console

# Shared state: subcommands read this to decide output format.
_output_format: OutputFormat = "table"


def get_output_format() -> OutputFormat:
    return _output_format


app = typer.Typer(
    name="gemstar",
    help="GemStar — AI-driven automated quantitative research framework.",
    no_args_is_help=True,
)

scheduler_app = typer.Typer(
    name="scheduler",
    help="Manage the automatic daily pipeline scheduler.",
    no_args_is_help=True,
)

engineering_app = typer.Typer(
    name="engineering",
    help="Inspect and execute bounded engineering tasks.",
    no_args_is_help=True,
)

live_app = typer.Typer(
    name="live",
    help="Run live trading radar commands.",
    no_args_is_help=True,
)


@app.callback()
def _global_options(
    output: OutputFormat = typer.Option(
        "table",
        "--output", "-o",
        help="Output format: table (human) or json (machine).",
    ),
) -> None:
    """Set global options."""
    global _output_format
    _output_format = output


# --- Register subcommands ---
from src.cli.commands.init_cmd import init_cmd  # noqa: E402
from src.cli.commands.run_cmd import run_cmd  # noqa: E402
from src.cli.commands.fetch_cmd import fetch_cmd  # noqa: E402
from src.cli.commands.status_cmd import status_cmd  # noqa: E402
from src.cli.commands.history_cmd import history_cmd  # noqa: E402
from src.cli.commands.list_cmd import roles_cmd, strategies_cmd, factors_cmd  # noqa: E402
from src.cli.commands.daemon_cmd import (  # noqa: E402
    start_cmd, stop_cmd, daemon_status_cmd, restart_cmd,
)
from src.cli.commands.doctor_cmd import doctor_cmd  # noqa: E402
from src.cli.commands.cleanup_cmd import cleanup_cmd  # noqa: E402
from src.cli.commands.leaderboard_cmd import leaderboard_cmd  # noqa: E402
from src.cli.commands.engineering_cmd import engineering_run_cmd  # noqa: E402
from src.cli.commands.live_cmd import live_once_cmd, live_start_cmd  # noqa: E402
from src.cli.commands.trade_cmd import trade_cmd  # noqa: E402

app.command("init")(init_cmd)
app.command("run")(run_cmd)
app.command("trade")(trade_cmd)
app.command("fetch")(fetch_cmd)
app.command("status")(status_cmd)
app.command("run-status", hidden=True)(status_cmd)
app.command("history")(history_cmd)
app.command("roles")(roles_cmd)
app.command("strategies")(strategies_cmd)
app.command("factors")(factors_cmd)
scheduler_app.command("start")(start_cmd)
scheduler_app.command("status")(daemon_status_cmd)
scheduler_app.command("stop")(stop_cmd)
scheduler_app.command("restart")(restart_cmd)
app.add_typer(scheduler_app, name="scheduler")
engineering_app.command("run")(engineering_run_cmd)
app.add_typer(engineering_app, name="engineering")
live_app.command("once")(live_once_cmd)
live_app.command("start")(live_start_cmd)
app.add_typer(live_app, name="live")
app.command("start", hidden=True)(start_cmd)
app.command("stop", hidden=True)(stop_cmd)
app.command("restart", hidden=True)(restart_cmd)
app.command("doctor")(doctor_cmd)
app.command("cleanup")(cleanup_cmd)
app.command("leaderboard")(leaderboard_cmd)


if __name__ == "__main__":
    app()
