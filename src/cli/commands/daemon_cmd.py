"""Scheduler command handlers — background daily pipeline management."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import typer

from src.cli.config import load_config
from src.cli.output import console

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 600  # 10 minutes
_PID_FILE = Path(".gemstar.pid")


# ── CLI commands ────────────────────────────────────────────────


def start_cmd(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (no detach)."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Start the daily pipeline scheduler."""
    config = _load_and_validate(config_path)

    if _is_running():
        console.print("[yellow]Daemon is already running.[/yellow]")
        console.print("Use [cyan]gemstar restart[/cyan] to restart, or [cyan]gemstar stop[/cyan] to stop.")
        raise typer.Exit(1)

    log_path = Path(config.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if foreground:
        _print_summary(config)
        _setup_logging(log_path)
        _run_daemon(config)
    else:
        pid = _daemonize(log_path)
        console.print("[green]Scheduler started.[/green]")
        console.print(f"  PID:  {pid}")
        console.print(f"  Log:  {log_path}")
        console.print(f"  Fetch: {config.schedule.fetch}  Run: {config.schedule.run}")
        console.print()
        console.print("[dim]Manage with: gemstar scheduler status | scheduler stop | scheduler restart[/dim]")


def stop_cmd() -> None:
    """Stop the daily pipeline scheduler."""
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Scheduler is not running.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Stopping scheduler (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print("[yellow]Process not found, cleaning up stale PID file.[/yellow]")
        _remove_pid()
        raise typer.Exit(0)
    except PermissionError:
        console.print("[red]Permission denied. Try running with sudo.[/red]")
        raise typer.Exit(1)

    # Wait up to 5 seconds for graceful shutdown
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        import time
        time.sleep(0.1)
    else:
        console.print("[yellow]Process did not exit, sending SIGKILL...[/yellow]")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    _remove_pid()
    console.print("[green]Scheduler stopped.[/green]")


def daemon_status_cmd() -> None:
    """Show scheduler process status."""
    pid = _read_pid()
    if pid is None:
        console.print("[dim]Scheduler is not running.[/dim]")
        raise typer.Exit(0)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        console.print(f"[yellow]Stale PID file (process {pid} not found).[/yellow]")
        _remove_pid()
        raise typer.Exit(0)

    config = load_config()
    try:
        uptime_s = datetime.now().timestamp() - os.path.getmtime(_PID_FILE)
        uptime = _format_duration(uptime_s)
    except OSError:
        uptime = "?"

    console.print(f"[green]Scheduler is running.[/green]")
    console.print(f"  PID:     {pid}")
    console.print(f"  Uptime:  {uptime}")
    if config.schedule:
        console.print(f"  Fetch:   {config.schedule.fetch}")
        console.print(f"  Run:     {config.schedule.run}")
    console.print(f"  Log:     {config.log_path}")


def restart_cmd(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (no detach)."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Restart the daily pipeline scheduler."""
    pid = _read_pid()
    if pid is not None:
        try:
            os.kill(pid, 0)
            console.print("Stopping current scheduler...")
            stop_cmd()
        except ProcessLookupError:
            _remove_pid()

    start_cmd(foreground=foreground, config_path=config_path)


# ── Helper functions ────────────────────────────────────────────


def _load_and_validate(config_path: str | None) -> "GemStarConfig":
    path = Path(config_path) if config_path else None
    config = load_config(path)
    if config.schedule is None:
        console.print("[red]No schedule configured in gemstar.yaml.[/red]")
        console.print('Set schedule: "收盘后" or schedule: "16:00" in your config.')
        raise typer.Exit(1)
    return config


def _is_running() -> bool:
    pid = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        _remove_pid()
        return False


def _read_pid() -> int | None:
    try:
        return int(_PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    _PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    try:
        _PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _setup_logging(log_path: Path) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s  %(message)s")
    fh = logging.FileHandler(str(log_path))
    fh.setFormatter(fmt)
    root.addHandler(fh)


def _print_summary(config) -> None:
    console.print(f"[cyan]GemStar scheduler[/cyan]")
    console.print(f"  Fetch: {config.schedule.fetch}")
    console.print(f"  Run:   {config.schedule.run}")
    console.print(f"  LLM:   {'on' if config.llm.available else 'off'}")
    console.print(f"  Auto-fetch: {'on' if config.data.auto_fetch else 'off'}")
    console.print()


def _daemonize(log_path: Path) -> int:
    """Double-fork to detach into background. Returns grandchild PID via PID file."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent — wait for grandchild to write PID file, then return its PID
        import time
        for _ in range(50):
            time.sleep(0.1)
            p = _read_pid()
            if p is not None:
                return p
        return pid  # fallback

    # Child — become session leader
    os.setsid()

    # Second fork — prevent re-acquiring a terminal
    pid = os.fork()
    if pid > 0:
        os._exit(0)  # first child exits

    # Grandchild — write our own PID so status/stop can find us
    _write_pid(os.getpid())

    # Redirect stdio to log file
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, sys.stdout.fileno())
    os.dup2(fd, sys.stderr.fileno())
    os.close(fd)

    # Set up logging so logger.info() etc. also go to the log file
    _setup_logging(log_path)

    # Run the daemon loop
    try:
        config = _load_and_validate(None)
        _run_daemon(config)
    except Exception:
        logger.exception("Daemon crashed")
    finally:
        _remove_pid()
        os._exit(0)


def _run_daemon(config) -> None:
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("Daemon started (fetch=%s, run=%s)", config.schedule.fetch, config.schedule.run)
    _run_loop(config, stop_event)
    logger.info("Daemon stopped")


# ── Core loop (mostly unchanged) ───────────────────────────────


def _run_loop(config, stop_event: threading.Event) -> None:
    """Main daemon loop."""
    schedule = config.schedule

    while not stop_event.is_set():
        today = date.today()
        today_str = today.strftime("%Y%m%d")
        logger.info("Checking schedule for %s...", today_str)

        # Check if today is a trading day
        if not _is_trading_day_cached(today_str, config, stop_event):
            logger.info("%s is not a trading day, sleeping until tomorrow", today_str)
            _sleep_until_tomorrow(stop_event)
            if stop_event.is_set():
                break
            continue

        # Check if today already completed
        from src.orchestrator.scheduler import last_run_status

        status = last_run_status(config.db_path, today_str)
        if status == "completed":
            logger.info("%s already completed, skipping", today_str)
            _sleep_until_tomorrow(stop_event)
            if stop_event.is_set():
                break
            continue

        # Wait for fetch time
        logger.info("Waiting until %s to fetch data...", schedule.fetch)
        if not _wait_or_stop(schedule.fetch, stop_event):
            break

        # Fetch data
        if config.data.auto_fetch:
            logger.info("Fetching data...")
            ok = _run_subcommand("fetch", config, stop_event)
            if not ok:
                logger.warning("Fetch failed, will retry with pipeline")

        # Wait for run time
        if schedule.run != schedule.fetch:
            logger.info("Waiting until %s to run pipeline...", schedule.run)
            if not _wait_or_stop(schedule.run, stop_event):
                break

        # Run pipeline with retries
        for attempt in range(1, _MAX_RETRIES + 1):
            logger.info("Running pipeline (attempt %d/%d)...", attempt, _MAX_RETRIES)
            ok = _run_subcommand("run", config, stop_event, llm=config.llm.available)
            if ok:
                logger.info("Pipeline completed")
                break
            if attempt < _MAX_RETRIES:
                logger.warning("Pipeline failed, retrying in %dmin...", _RETRY_DELAY // 60)
                if not _wait_seconds(_RETRY_DELAY, stop_event):
                    break
        else:
            logger.error("Pipeline failed after %d attempts", _MAX_RETRIES)

        # Sleep until tomorrow
        _sleep_until_tomorrow(stop_event)


def _is_trading_day_cached(date_str: str, config, stop_event: threading.Event) -> bool:
    """Check trading day using cached trade calendar."""
    try:
        from src.data.fetcher import init_tushare, fetch_trade_calendar

        pro = init_tushare(config.tushare_token or None)
        d = datetime.strptime(date_str, "%Y%m%d").date()
        start = (d - timedelta(days=7)).strftime("%Y%m%d")
        end = (d + timedelta(days=7)).strftime("%Y%m%d")
        cal = fetch_trade_calendar(pro, start, end)

        from src.orchestrator.scheduler import is_trading_day

        result = is_trading_day(date_str, cal)
        logger.info("Trade calendar check: %s is %s", date_str, "trading day" if result else "non-trading day")
        return result
    except Exception as e:
        logger.warning("Trade calendar check failed: %s — falling back to weekday heuristic", e)
        d = datetime.strptime(date_str, "%Y%m%d").date()
        result = d.weekday() < 5
        logger.info("Weekday heuristic: %s (weekday=%d) → %s", date_str, d.weekday(), "trading day" if result else "non-trading day")
        return result


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
            timeout=3600,
            cwd=None,
        )
        if result.returncode == 0:
            logger.info("%s finished successfully", subcmd)
        else:
            logger.warning("%s exited with code %d", subcmd, result.returncode)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after 1 hour", subcmd)
        return False
    except Exception as e:
        logger.error("%s error: %s", subcmd, e)
        return False


def _wait_or_stop(target_time: str, stop_event: threading.Event) -> bool:
    """Wait until target_time. Returns True if time reached, False if stopped."""
    from src.orchestrator.scheduler import wait_until
    return wait_until(target_time, stop_event=stop_event)


def _wait_seconds(seconds: int, stop_event: threading.Event) -> bool:
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
        logger.info("Sleeping until %s...", tomorrow.strftime("%Y-%m-%d %H:%M"))
        _wait_seconds(seconds, stop_event)


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m}m"
