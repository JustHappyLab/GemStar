"""Tests for orchestrator/run_manifest.py — run lifecycle tracking."""

import json
from pathlib import Path

import pytest

from src.orchestrator.run_manifest import finalize_run, record_step, start_run
from src.orchestrator.state_db import connect, migrate


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp_path: Path) -> str:
    """Create a migrated SQLite DB path under tmp_path."""
    db_path = str(tmp_path / "test.db")
    conn = connect(db_path)
    migrate(conn)
    conn.close()
    return db_path


def _count_rows(db_path: str, table: str) -> int:
    conn = connect(db_path)
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_start_run_creates_db_row_and_directory(tmp_path: Path):
    """start_run() inserts a run row and creates the artifacts directory."""
    db_path = _setup_db(tmp_path)
    artifacts_dir = str(tmp_path / "artifacts")

    run_id = start_run("r1", db_path=db_path, artifacts_dir=artifacts_dir)

    assert run_id == "r1"
    # DB row exists
    assert _count_rows(db_path, "runs") == 1
    conn = connect(db_path)
    row = conn.execute("SELECT status FROM runs WHERE run_id = 'r1'").fetchone()
    conn.close()
    assert row[0] == "running"
    # Artifacts directory exists
    assert (tmp_path / "artifacts" / "r1").is_dir()


def test_record_step_inserts_step_row(tmp_path: Path):
    """record_step() inserts a step row linked to the run."""
    db_path = _setup_db(tmp_path)
    start_run("r1", db_path=db_path, artifacts_dir=str(tmp_path / "artifacts"))

    record_step("r1", "s1", role="collector", status="started", db_path=db_path)

    assert _count_rows(db_path, "steps") == 1
    conn = connect(db_path)
    row = conn.execute(
        "SELECT step_id, role, status FROM steps WHERE run_id = 'r1'"
    ).fetchone()
    conn.close()
    assert row == ("s1", "collector", "started")


def test_finalize_run_updates_status_and_writes_manifest(tmp_path: Path):
    """finalize_run() sets the run status to completed and writes run_manifest.json."""
    db_path = _setup_db(tmp_path)
    artifacts_dir = str(tmp_path / "artifacts")
    start_run("r1", db_path=db_path, artifacts_dir=artifacts_dir)
    record_step("r1", "s1", role="collector", status="done", db_path=db_path)

    finalize_run("r1", status="completed", db_path=db_path, artifacts_dir=artifacts_dir)

    # DB row updated
    conn = connect(db_path)
    row = conn.execute("SELECT status, finished_at FROM runs WHERE run_id = 'r1'").fetchone()
    conn.close()
    assert row[0] == "completed"
    assert row[1] is not None
    # Manifest file written
    manifest_path = tmp_path / "artifacts" / "r1" / "run_manifest.json"
    assert manifest_path.exists()


def test_full_lifecycle_manifest_content(tmp_path: Path):
    """Full lifecycle: start -> record steps -> finalize -> verify manifest JSON."""
    db_path = _setup_db(tmp_path)
    artifacts_dir = str(tmp_path / "artifacts")

    start_run("r-full", db_path=db_path, artifacts_dir=artifacts_dir)
    record_step("r-full", "collect", role="collector", status="done", db_path=db_path)
    record_step("r-full", "analyze", role="analyst", status="done", db_path=db_path)
    finalize_run("r-full", status="completed", db_path=db_path, artifacts_dir=artifacts_dir)

    manifest_path = tmp_path / "artifacts" / "r-full" / "run_manifest.json"
    data = json.loads(manifest_path.read_text())

    assert data["version"] == "RunManifestV1"
    assert data["run_id"] == "r-full"
    assert data["status"] == "completed"
    assert data["step_statuses"] == {"collect": "done", "analyze": "done"}
    assert data["started_at"] is not None
    assert data["finished_at"] is not None


def test_start_run_custom_paths(tmp_path: Path):
    """start_run() works with explicit non-default db_path and artifacts_dir."""
    custom_db = str(tmp_path / "custom" / "my.db")
    custom_art = str(tmp_path / "custom_artifacts")
    # Pre-create parent for db
    Path(custom_db).parent.mkdir(parents=True, exist_ok=True)
    # Migrate the DB at the custom path
    conn = connect(custom_db)
    migrate(conn)
    conn.close()

    run_id = start_run("r-custom", db_path=custom_db, artifacts_dir=custom_art)

    assert run_id == "r-custom"
    assert (Path(custom_art) / "r-custom").is_dir()
    conn = connect(custom_db)
    row = conn.execute("SELECT status FROM runs WHERE run_id = 'r-custom'").fetchone()
    conn.close()
    assert row[0] == "running"


def test_finalize_run_nonexistent_run(tmp_path: Path):
    """finalize_run() on a non-existent run_id still writes manifest (no crash)."""
    db_path = _setup_db(tmp_path)
    artifacts_dir = str(tmp_path / "artifacts")

    finalize_run("ghost-run", status="failed", db_path=db_path, artifacts_dir=artifacts_dir)

    # DB is untouched — no run row was ever inserted
    assert _count_rows(db_path, "runs") == 0
    # Manifest file is still written (mkdir guard creates the directory)
    manifest_path = tmp_path / "artifacts" / "ghost-run" / "run_manifest.json"
    assert manifest_path.exists()
