"""Tests for gemstar reset command."""

from __future__ import annotations

import sqlite3

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod
    app_mod._output_format = "table"


def _write_config(tmp_path) -> None:
    tmp_path.joinpath("gemstar.yaml").write_text(
        "db_path: state.db\n"
        "artifacts_dir: artifacts\n"
        "strategies:\n"
        "  - strategies/chinext_lstm_mf8/config.yaml\n",
        encoding="utf-8",
    )


def test_reset_trade_backs_up_and_clears_paper_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    tmp_path.joinpath("alerts").mkdir()
    tmp_path.joinpath("alerts", "ledger.jsonl").write_text("ledger\n", encoding="utf-8")
    tmp_path.joinpath("alerts", "live.jsonl").write_text("alert\n", encoding="utf-8")
    current = tmp_path / "artifacts" / "current"
    current.mkdir(parents=True)
    current.joinpath("trade_status.json").write_text("{}", encoding="utf-8")
    current.joinpath("trade_status.md").write_text("status", encoding="utf-8")

    _reset_output_format()
    result = runner.invoke(app, ["reset", "trade", "--yes"])

    assert result.exit_code == 0, result.output
    assert not tmp_path.joinpath("alerts", "ledger.jsonl").exists()
    assert tmp_path.joinpath("alerts", "live.jsonl").exists()
    assert not current.joinpath("trade_status.json").exists()
    assert not current.joinpath("trade_status.md").exists()
    backup = next(tmp_path.joinpath("reset-backups").iterdir())
    assert backup.joinpath("alerts", "ledger.jsonl").read_text(encoding="utf-8") == "ledger\n"
    assert backup.joinpath("artifacts", "current", "trade_status.md").exists()


def test_reset_trade_include_alerts_clears_notification_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    tmp_path.joinpath("alerts").mkdir()
    tmp_path.joinpath("alerts", "ledger.jsonl").write_text("ledger\n", encoding="utf-8")
    tmp_path.joinpath("alerts", "live.jsonl").write_text("alert\n", encoding="utf-8")

    _reset_output_format()
    result = runner.invoke(app, ["reset", "trade", "--include-alerts", "--yes"])

    assert result.exit_code == 0, result.output
    assert not tmp_path.joinpath("alerts", "ledger.jsonl").exists()
    assert not tmp_path.joinpath("alerts", "live.jsonl").exists()
    backup = next(tmp_path.joinpath("reset-backups").iterdir())
    assert backup.joinpath("alerts", "live.jsonl").read_text(encoding="utf-8") == "alert\n"


def test_reset_all_clears_runs_and_artifacts_but_keeps_data_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    tmp_path.joinpath("alerts").mkdir()
    tmp_path.joinpath("alerts", "ledger.jsonl").write_text("ledger\n", encoding="utf-8")
    tmp_path.joinpath("alerts", "live.jsonl").write_text("alert\n", encoding="utf-8")
    tmp_path.joinpath("data", "raw").mkdir(parents=True)
    tmp_path.joinpath("data", "raw", "cache.parquet").write_text("cache", encoding="utf-8")
    run_dir = tmp_path / "artifacts" / "run-1"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("leaderboard.json").write_text("{}", encoding="utf-8")

    conn = sqlite3.connect(tmp_path / "state.db")
    conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT)")
    conn.execute("CREATE TABLE steps (run_id TEXT, step_id TEXT)")
    conn.execute("INSERT INTO runs (run_id, started_at, status) VALUES ('run-1', '2026-06-04T00:00:00', 'completed')")
    conn.execute("INSERT INTO steps (run_id, step_id) VALUES ('run-1', 'x')")
    conn.commit()
    conn.close()

    _reset_output_format()
    result = runner.invoke(app, ["reset", "all", "--yes"])

    assert result.exit_code == 0, result.output
    assert not tmp_path.joinpath("alerts", "ledger.jsonl").exists()
    assert not tmp_path.joinpath("alerts", "live.jsonl").exists()
    assert not run_dir.exists()
    assert tmp_path.joinpath("data", "raw", "cache.parquet").exists()
    conn = sqlite3.connect(tmp_path / "state.db")
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 0
    conn.close()
