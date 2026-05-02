"""Run manifest writer: tracks daily run lifecycle in state.db + artifacts/.

CALLING SPEC:
    start_run(run_id, db_path="state.db") -> str
        Inserts a running row in `runs`, creates artifacts/<run_id>/, returns run_id.

    record_step(run_id, step_id, role, status, ...) -> None
        Upserts a step row in `steps`.

    finalize_run(run_id, status, db_path="state.db") -> None
        Updates the run row to finished and writes run_manifest.json.

SIDE EFFECTS:
    Writes to state.db and artifacts/<run_id>/run_manifest.json.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from src.orchestrator.state_db import connect


def start_run(run_id: str, db_path: str = "state.db", artifacts_dir: str = "artifacts") -> str:
    now = datetime.now().isoformat()
    conn = connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at, status) VALUES (?, ?, 'running')",
        (run_id, now),
    )
    conn.commit()
    conn.close()
    Path(artifacts_dir, run_id).mkdir(parents=True, exist_ok=True)
    return run_id


def record_step(
    run_id: str,
    step_id: str,
    role: str = "",
    status: str = "pending",
    artifact_uri: str = "",
    error: str = "",
    db_path: str = "state.db",
) -> None:
    now = datetime.now().isoformat()
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO steps (run_id, step_id, role, status, started_at, artifact_uri, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, step_id, role, status, now, artifact_uri, error),
    )
    conn.commit()
    conn.close()


def finalize_run(
    run_id: str,
    status: str = "completed",
    db_path: str = "state.db",
    artifacts_dir: str = "artifacts",
) -> None:
    now = datetime.now().isoformat()
    conn = connect(db_path)
    conn.execute(
        "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
        (now, status, run_id),
    )
    conn.commit()

    cursor = conn.execute("SELECT step_id, status FROM steps WHERE run_id = ?", (run_id,))
    step_statuses = dict(cursor.fetchall())
    conn.close()

    from src.schemas.manifest import RunManifestV1
    manifest = RunManifestV1(
        run_id=run_id,
        started_at=datetime.fromisoformat(now),
        finished_at=datetime.fromisoformat(now),
        status=status,
        step_statuses=step_statuses,
    )
    manifest_path = Path(artifacts_dir, run_id, "run_manifest.json")
    manifest_path.write_text(manifest.model_dump_json(indent=2))
