from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS puzzle_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    puzzle_key TEXT NOT NULL,
    puzzle_date TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    UNIQUE (puzzle_key, puzzle_date)
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    puzzle_instance_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    sandbox_type TEXT NOT NULL,
    sandbox_session_id TEXT,
    prompt_config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    solve_status TEXT,
    normalized_score REAL,
    raw_metrics_json TEXT,
    failure_category TEXT,
    latency_ms INTEGER NOT NULL,
    token_usage_json TEXT NOT NULL,
    cost_estimate_usd REAL NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (puzzle_instance_id) REFERENCES puzzle_instances (id)
);

CREATE TABLE IF NOT EXISTS attempt_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    action_kind TEXT NOT NULL,
    action_payload_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    observation_json TEXT NOT NULL,
    artifacts_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES benchmark_runs (id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES benchmark_runs (id)
);

CREATE TABLE IF NOT EXISTS leaderboard_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leaderboard_date TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    average_score REAL NOT NULL,
    solve_rate REAL NOT NULL,
    puzzle_count INTEGER NOT NULL,
    average_latency_ms REAL NOT NULL,
    average_cost_usd REAL NOT NULL,
    UNIQUE (leaderboard_date, provider, model_id)
);
"""


def connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def reset_db(db_path: Path | None = None) -> None:
    target = db_path or get_settings().db_path
    if target.exists():
        target.unlink()
