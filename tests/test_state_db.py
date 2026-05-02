"""Tests for state database migrations and basic CRUD."""

import tempfile
from pathlib import Path

from src.orchestrator.state_db import connect, migrate


def _tables(conn):
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def test_migrate_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = connect(db_path)
        tables = _tables(conn)
        conn.close()
        for t in ("runs", "steps", "artifacts", "strategies", "factors", "incidents", "costs"):
            assert t in tables, f"Missing table: {t}"


def test_migrate_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = connect(db_path)
        migrate(conn)  # second call should be a no-op
        tables = _tables(conn)
        assert len(tables) == 7 + len([t for t in tables if t == "sqlite_sequence"])
        conn.close()


def test_runs_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = connect(db_path)
        conn.execute("INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, ?)",
                      ("run_001", "2026-05-03T22:00:00", "running"))
        conn.commit()
        row = conn.execute("SELECT status FROM runs WHERE run_id = 'run_001'").fetchone()
        assert row[0] == "running"

        conn.execute("UPDATE runs SET status = 'completed' WHERE run_id = 'run_001'")
        conn.commit()
        row = conn.execute("SELECT status FROM runs WHERE run_id = 'run_001'").fetchone()
        assert row[0] == "completed"
        conn.close()


def test_steps_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        conn = connect(db_path)
        conn.execute("INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, ?)",
                      ("run_002", "2026-05-03T22:00:00", "running"))
        conn.execute(
            "INSERT INTO steps (run_id, step_id, role, status) VALUES (?, ?, ?, ?)",
            ("run_002", "collecting", "orchestrator", "started"),
        )
        conn.commit()
        rows = conn.execute("SELECT step_id, status FROM steps WHERE run_id = 'run_002'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "collecting"
        conn.close()
