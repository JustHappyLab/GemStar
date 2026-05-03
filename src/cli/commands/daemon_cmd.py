"""gemstar daemon — built-in scheduler for automated daily pipeline runs."""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta

import typer

from src.cli.config import load_config
from src.cli.output import console

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 600  # 10 minutes


def daemon_cmd(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (no detach)."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Start the scheduler daemon for automated daily pipeline runs."""
    from src.cli.config import find_config

    config = load_config()

    if config.schedule is None:
        console.print("[red]No schedule configured in gemstar.yaml.[/red]")
        console.print('Set schedule: "收盘后" or schedule: "16:00" in your config.')
        raise typer.Exit(1)

    console.print(f"[cyan]GemStar daemon[/cyan]")
    console.print(f"  Fetch: {config.schedule.fetch}")
    console.print(f"  Run:   {config.schedule.run}")
    console.print(f"  LLM:   {'on' if config.llm.available else 'off'}")
    console.print(f"  Auto-fetch: {'on' if config.data.auto_fetch else 'off'}")
    console.print()

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        console.print("\n[yellow]Shutting down gracefully...[/yellow]")
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    _run_loop(config, stop_event)


def _run_loop(config, stop_event: threading.Event) -> None:
    """Main daemon loop."""
    schedule = config.schedule
    today_str = date.today().strftime("%Y%m%d")

    while not stop_event.is_set():
        today = date.today()
        today_str = today.strftime("%Y%m%d")

        # Check if today is a trading day
        if not _is_trading_day_cached(today_str, config, stop_event):
            _sleep_until_tomorrow(stop_event)
            if stop_event.is_set():
                break
            continue

        # Check if today already completed
        from src.orchestrator.scheduler import last_run_status

        status = last_run_status(config.db_path, today_str)
        if status == "completed":
            console.print(f"[dim]{today_str} already completed, skipping[/dim]")
            _sleep_until_tomorrow(stop_event)
            if stop_event.is_set():
                break
            continue

        # Wait for fetch time
        console.print(f"[dim]Waiting until {schedule.fetch} to fetch data...[/dim]")
        if not _wait_or_stop(schedule.fetch, stop_event):
            break

        # Fetch data
        if config.data.auto_fetch:
            console.print(f"[cyan]{_now_str()} Fetching data...[/cyan]")
            ok = _run_subcommand("fetch", config, stop_event)
            if not ok:
                console.print("[yellow]Fetch failed, will retry with pipeline[/yellow]")

        # Wait for run time
        if schedule.run != schedule.fetch:
            console.print(f"[dim]Waiting until {schedule.run} to run pipeline...[/dim]")
            if not _wait_or_stop(schedule.run, stop_event):
                break

        # Run pipeline with retries
        for attempt in range(1, _MAX_RETRIES + 1):
            console.print(f"[cyan]{_now_str()} Running pipeline (attempt {attempt}/{_MAX_RETRIES})...[/cyan]")
            ok = _run_subcommand("run", config, stop_event, llm=config.llm.available)
            if ok:
                console.print(f"[green]{_now_str()} Pipeline completed[/green]")
                break
            if attempt < _MAX_RETRIES:
                console.print(f"[yellow]Pipeline failed, retrying in {_RETRY_DELAY // 60}min...[/yellow]")
                if not _wait_seconds(_RETRY_DELAY, stop_event):
                    break
        else:
            console.print(f"[red]{_now_str()} Pipeline failed after {_MAX_RETRIES} attempts[/red]")

        # Sleep until tomorrow
        _sleep_until_tomorrow(stop_event)

    console.print("[dim]Daemon stopped[/dim]")


def _is_trading_day_cached(date_str: str, config, stop_event: threading.Event) -> bool:
    """Check trading day using cached trade calendar."""
    try:
        from src.data.fetcher import init_tushare, fetch_trade_calendar

        pro = init_tushare(config.tushare_token or None)
        # Fetch a small window around today
        d = datetime.strptime(date_str, "%Y%m%d").date()
        start = (d - timedelta(days=7)).strftime("%Y%m%d")
        end = (d + timedelta(days=7)).strftime("%Y%m%d")
        cal = fetch_trade_calendar(pro, start, end)

        from src.orchestrator.scheduler import is_trading_day

        return is_trading_day(date_str, cal)
    except Exception as e:
        logger.warning("Trade calendar check failed: %s — assuming trading day", e)
        # Fallback: assume weekdays are trading days
        d = datetime.strptime(date_str, "%Y%m%d").date()
        return d.weekday() < 5


def _run_subcommand(
    subcmd: str,
    config,
    stop_event: threading.Event,
    llm: bool = False,
) -> bool:
    """Run a gemstar subcommand as a subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "src.cli.app", subcmd]
    if llm:
        cmd.append("--llm")

    try:
        result = subprocess.run(
            cmd,
            timeout=3600,  # 1 hour max per subcommand
            cwd=None,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        console.print(f"[red]{subcmd} timed out after 1 hour[/red]")
        return False
    except Exception as e:
        console.print(f"[red]{subcmd} error: {e}[/red]")
        return False


def _wait_or_stop(target_time: str, stop_event: threading.Event) -> bool:
    """Wait until target_time. Returns True if time reached, False if stopped."""
    from src.orchestrator.scheduler import wait_until

    return wait_until(target_time, stop_event=stop_event)


def _wait_seconds(seconds: int, stop_event: threading.Event) -> bool:
    """Wait for a number of seconds. Returns True if time reached, False if stopped."""
    return _wait_seconds_impl(seconds, stop_event)


def _wait_seconds_impl(seconds: int, stop_event: threading.Event) -> bool:
    end = datetime.now() + timedelta(seconds=seconds)
    while True:
        remaining = (end - datetime.now()).total_seconds()
        if remaining <= 0:
            return True
        if stop_event.is_set():
            return False
        stop_event.wait(min(30, remaining))
        if stop_event.is_set():
            return False


def _sleep_until_tomorrow(stop_event: threading.Event) -> None:
    """Sleep until 00:00:30 of the next day."""
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
    seconds = (tomorrow - now).total_seconds()
    if seconds > 0:
        console.print(f"[dim]Sleeping until {tomorrow.strftime('%Y-%m-%d %H:%M')}...[/dim]")
        _wait_seconds_impl(seconds, stop_event)


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")
