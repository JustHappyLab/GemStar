"""Tests for CLI init, status, and history commands."""

from __future__ import annotations

import sqlite3

import yaml
from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path, db_path: str = "state.db") -> None:
    """Write a minimal gemstar.yaml pointing at *db_path*."""
    cfg = {
        "tushare_token": "test",
        "benchmark": "399006.SZ",
        "db_path": db_path,
        "artifacts_dir": "artifacts",
        "data_cache_dir": "data/raw",
    }
    (tmp_path / "gemstar.yaml").write_text(yaml.dump(cfg))


def _create_db(path, runs=None, steps=None) -> None:
    """Create a state.db with optional seed data."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            config TEXT
        );
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            step_id TEXT NOT NULL,
            role TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            artifact_uri TEXT,
            latency_sec REAL,
            error TEXT
        );
    """)
    for r in (runs or []):
        conn.execute(
            "INSERT INTO runs (run_id, started_at, finished_at, status) VALUES (?,?,?,?)",
            r,
        )
    for s in (steps or []):
        conn.execute(
            "INSERT INTO steps (run_id, step_id, role, status, latency_sec, error) VALUES (?,?,?,?,?,?)",
            s,
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


def test_init_creates_config_and_db(tmp_path, monkeypatch):
    """gemstar init creates gemstar.yaml and state.db."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert (tmp_path / "gemstar.yaml").exists()
    assert (tmp_path / "state.db").exists()
    assert "Created config" in result.output
    assert "Migrated state DB" in result.output


def test_init_when_config_already_exists(tmp_path, monkeypatch):
    """gemstar init when gemstar.yaml already exists shows a warning, no crash."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gemstar.yaml").write_text("tushare_token: test\n")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert "Config already exists" in result.output
    # state.db should still be created / migrated
    assert (tmp_path / "state.db").exists()


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_no_runs(tmp_path, monkeypatch):
    """gemstar status with an empty DB shows 'No runs found'."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(tmp_path / "state.db")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_status_shows_run_details(tmp_path, monkeypatch):
    """gemstar status with a run in the DB shows run details."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(
        tmp_path / "state.db",
        runs=[("run-001", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "completed")],
        steps=[("run-001", "fetch", "fetcher", "completed", 12.5, None)],
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "run-001" in result.output
    assert "completed" in result.output
    assert "fetch" in result.output


def test_status_specific_run(tmp_path, monkeypatch):
    """gemstar status <run_id> for a specific run shows that run."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(
        tmp_path / "state.db",
        runs=[
            ("aaa", "2026-01-01T00:00:00", None, "running"),
            ("bbb", "2026-01-02T00:00:00", "2026-01-02T01:00:00", "completed"),
        ],
    )

    result = runner.invoke(app, ["status", "bbb"])

    assert result.exit_code == 0
    assert "bbb" in result.output
    assert "completed" in result.output


def test_status_nonexistent_run(tmp_path, monkeypatch):
    """gemstar status <run_id> for a non-existent run exits with error."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(tmp_path / "state.db")

    result = runner.invoke(app, ["status", "does-not-exist"])

    assert result.exit_code == 1
    assert "Run not found" in result.output


def test_status_no_state_db(tmp_path, monkeypatch):
    """gemstar status when state.db does not exist exits with error."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    # Do NOT create state.db

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "No state.db found" in result.output


# ---------------------------------------------------------------------------
# history command
# ---------------------------------------------------------------------------


def test_history_no_runs(tmp_path, monkeypatch):
    """gemstar history with an empty DB shows 'No runs found'."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(tmp_path / "state.db")

    result = runner.invoke(app, ["history"])

    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_history_lists_multiple_runs(tmp_path, monkeypatch):
    """gemstar history with multiple runs shows them all."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(
        tmp_path / "state.db",
        runs=[
            ("r1", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "completed"),
            ("r2", "2026-01-02T00:00:00", "2026-01-02T01:00:00", "failed"),
            ("r3", "2026-01-03T00:00:00", None, "running"),
        ],
    )

    result = runner.invoke(app, ["history"])

    assert result.exit_code == 0
    assert "r1" in result.output
    assert "r2" in result.output
    assert "r3" in result.output


def test_history_limit(tmp_path, monkeypatch):
    """gemstar history --limit 1 returns only one run."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _create_db(
        tmp_path / "state.db",
        runs=[
            ("r1", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "completed"),
            ("r2", "2026-01-02T00:00:00", "2026-01-02T01:00:00", "failed"),
        ],
    )

    result = runner.invoke(app, ["history", "--limit", "1"])

    assert result.exit_code == 0
    # Only the most recent run (r2) should appear
    assert "r2" in result.output
    assert "r1" not in result.output
