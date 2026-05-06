"""Tests for CLI scheduler commands — config validation and help."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod
    app_mod._output_format = "table"


def test_scheduler_help():
    """gemstar scheduler --help shows scheduler subcommands."""
    _reset_output_format()
    result = runner.invoke(app, ["scheduler", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output.lower()
    assert "status" in result.output.lower()


def test_scheduler_start_no_schedule_exits(tmp_path, monkeypatch):
    """gemstar scheduler start exits with error if no schedule configured."""
    monkeypatch.chdir(tmp_path)
    # Write a config without schedule
    tmp_path.joinpath("gemstar.yaml").write_text(
        "tushare_token: test\nschedule: null\n"
    )
    _reset_output_format()

    result = runner.invoke(app, ["scheduler", "start"])
    assert result.exit_code == 1
    assert "schedule" in result.output.lower() or "No schedule" in result.output


def test_scheduler_start_with_schedule_config(tmp_path, monkeypatch):
    """gemstar scheduler start works if schedule is configured (foreground mode, quick exit)."""
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

    result = runner.invoke(app, ["scheduler", "start", "--foreground"])
    # Should start and print schedule info before being interrupted
    assert "15:30" in result.output or "fetch" in result.output.lower() or result.exit_code == 0


def test_root_start_alias_still_supported(tmp_path, monkeypatch):
    """gemstar start remains as a compatibility alias for scheduler start."""
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath("gemstar.yaml").write_text(
        "tushare_token: test\nschedule: null\n"
    )
    _reset_output_format()

    result = runner.invoke(app, ["start"])
    assert result.exit_code == 1
    assert "schedule" in result.output.lower()


def test_run_subcommand_forwards_config_path(monkeypatch, tmp_path):
    """Scheduler subprocesses must use the same custom config as the parent."""
    from src.cli.commands import daemon_cmd

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(daemon_cmd.subprocess, "run", fake_run)

    ok = daemon_cmd._run_subcommand(
        "run",
        config=SimpleNamespace(llm=SimpleNamespace(enabled=True)),
        stop_event=None,
        llm=True,
        config_path=str(tmp_path / "custom.yaml"),
    )

    assert ok is True
    assert captured["cmd"] == [
        daemon_cmd.sys.executable,
        "-m",
        "src.cli.app",
        "run",
        "--config",
        str(tmp_path / "custom.yaml"),
        "--llm",
    ]
