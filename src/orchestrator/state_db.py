"""SQLite state database for run lifecycle tracking.

CALLING SPEC:
    connect(path="state.db") -> sqlite3.Connection
        Opens a connection with WAL mode and runs migrations.

    migrate(conn) -> None
        Creates all 7 tables if they don't exist.

SIDE EFFECTS:
    Creates/migrates the SQLite database file.
"""

import sqlite3
from pathlib import Path

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    config        TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    step_id       TEXT NOT NULL,
    role          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    started_at    TEXT,
    finished_at   TEXT,
    artifact_uri  TEXT,
    latency_sec   REAL,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    uri           TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    step_id       TEXT,
    sha256        TEXT,
    schema_name   TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategies (
    strategy_id   TEXT PRIMARY KEY,
    state         TEXT NOT NULL DEFAULT 'draft',
    updated_at    TEXT NOT NULL,
    config_uri    TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS factors (
    factor_id     TEXT PRIMARY KEY,
    state         TEXT NOT NULL DEFAULT 'candidate',
    updated_at    TEXT NOT NULL,
    ic_mean       REAL,
    ic_ir         REAL,
    coverage      REAL,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS incidents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    step_id       TEXT,
    error_class   TEXT,
    severity      TEXT,
    status        TEXT NOT NULL DEFAULT 'detected',
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS costs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    cost_type     TEXT NOT NULL,
    amount_tokens INTEGER,
    amount_usd    REAL,
    recorded_at   TEXT NOT NULL
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


def connect(path: str | Path = "state.db") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn
