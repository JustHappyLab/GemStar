"""Tests for CLI daemon command — config validation and help."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod
    app_mod._output_format = "table"


def test_daemon_help():
    """gemstar daemon --help shows schedule info."""
    _reset_output_format()
    result = runner.invoke(app, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "scheduler" in result.output.lower() or "daemon" in result.output.lower()


def test_daemon_no_schedule_exits(tmp_path, monkeypatch):
    """gemstar daemon exits with error if no schedule configured."""
    monkeypatch.chdir(tmp_path)
    # Write a config without schedule
    tmp_path.joinpath("gemstar.yaml").write_text(
        "tushare_token: test\nschedule: null\n"
    )
    _reset_output_format()

    result = runner.invoke(app, ["daemon"])
    assert result.exit_code == 1
    assert "schedule" in result.output.lower() or "No schedule" in result.output


def test_daemon_with_schedule_config(tmp_path, monkeypatch):
    """gemstar daemon starts if schedule is configured (foreground mode, quick exit)."""
    import signal
    import threading

    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath("gemstar.yaml").write_text(
        'tushare_token: test\nschedule: "收盘后"\n'
    )
    _reset_output_format()

    # Use a timer to send SIGINT after a short delay
    def _send_interrupt():
        import time
        time.sleep(1)
        import os
        os.kill(os.getpid(), signal.SIGINT)

    t = threading.Thread(target=_send_interrupt, daemon=True)
    t.start()

    result = runner.invoke(app, ["daemon", "--foreground"])
    # Should start and print schedule info before being interrupted
    assert "15:30" in result.output or "fetch" in result.output.lower() or result.exit_code == 0
