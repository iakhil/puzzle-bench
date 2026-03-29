from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from .db import connect
from .domain import Observation, PuzzleInstance, ScoredAttempt


def upsert_puzzle_instance(puzzle: PuzzleInstance) -> int:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO puzzle_instances (puzzle_key, puzzle_date, display_name, source_url, snapshot_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (puzzle_key, puzzle_date) DO UPDATE SET
                display_name = excluded.display_name,
                source_url = excluded.source_url,
                snapshot_json = excluded.snapshot_json
            """,
            (
                puzzle.puzzle_key,
                puzzle.date.isoformat(),
                puzzle.display_name,
                puzzle.source_url,
                json.dumps(puzzle.snapshot_data, sort_keys=True),
            ),
        )
        row = conn.execute(
            "SELECT id FROM puzzle_instances WHERE puzzle_key = ? AND puzzle_date = ?",
            (puzzle.puzzle_key, puzzle.date.isoformat()),
        ).fetchone()
    return int(row["id"])


def get_puzzle_instance_id(puzzle_key: str, puzzle_date: date) -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM puzzle_instances WHERE puzzle_key = ? AND puzzle_date = ?",
            (puzzle_key, puzzle_date.isoformat()),
        ).fetchone()
    return None if row is None else int(row["id"])


def insert_run(
    run_id: str,
    puzzle_instance_id: int,
    provider: str,
    model_id: str,
    sandbox_type: str,
    prompt_config_hash: str,
    started_at: str,
    sandbox_session_id: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_runs (
                id, puzzle_instance_id, provider, model_id, sandbox_type, sandbox_session_id,
                prompt_config_hash, status, latency_ms, token_usage_json, cost_estimate_usd, started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', 0, '{}', 0.0, ?)
            """,
            (run_id, puzzle_instance_id, provider, model_id, sandbox_type, sandbox_session_id, prompt_config_hash, started_at),
        )


def update_run_result(
    run_id: str,
    status: str,
    scored_attempt: ScoredAttempt,
    latency_ms: int,
    token_usage: dict[str, Any],
    cost_estimate_usd: float,
    completed_at: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE benchmark_runs
            SET status = ?, solve_status = ?, normalized_score = ?, raw_metrics_json = ?,
                failure_category = ?, latency_ms = ?, token_usage_json = ?, cost_estimate_usd = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                status,
                scored_attempt.solve_status,
                scored_attempt.normalized_score,
                json.dumps(scored_attempt.raw_metrics, sort_keys=True),
                scored_attempt.failure_category,
                latency_ms,
                json.dumps(token_usage, sort_keys=True),
                cost_estimate_usd,
                completed_at,
                run_id,
            ),
        )


def mark_run_failed(
    run_id: str,
    failure_category: str,
    completed_at: str,
    raw_metrics: dict[str, Any] | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE benchmark_runs
            SET status = 'failed',
                solve_status = 'failed',
                normalized_score = 0.0,
                raw_metrics_json = ?,
                failure_category = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(raw_metrics or {}, sort_keys=True),
                failure_category,
                completed_at,
                run_id,
            ),
        )


def add_attempt_step(
    run_id: str,
    step_index: int,
    action_kind: str,
    action_payload: dict[str, Any],
    rationale: str,
    observation: Observation,
    artifacts: dict[str, Any],
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO attempt_steps (
                run_id, step_index, action_kind, action_payload_json, rationale, observation_json, artifacts_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step_index,
                action_kind,
                json.dumps(action_payload, sort_keys=True),
                rationale,
                json.dumps(observation.__dict__, sort_keys=True),
                json.dumps(artifacts, sort_keys=True),
            ),
        )


def add_artifact(run_id: str, artifact_type: str, path: str, metadata: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO artifacts (run_id, artifact_type, path, metadata_json) VALUES (?, ?, ?, ?)",
            (run_id, artifact_type, path, json.dumps(metadata, sort_keys=True)),
        )


def recompute_daily_leaderboard(target_date: date) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM leaderboard_daily WHERE leaderboard_date = ?", (target_date.isoformat(),))
        conn.execute(
            """
            WITH latest_runs AS (
                SELECT
                    br.id,
                    br.provider,
                    br.model_id,
                    br.normalized_score,
                    br.solve_status,
                    br.latency_ms,
                    br.cost_estimate_usd,
                    pi.puzzle_date,
                    pi.puzzle_key,
                    ROW_NUMBER() OVER (
                        PARTITION BY pi.puzzle_date, pi.puzzle_key, br.provider, br.model_id
                        ORDER BY COALESCE(br.completed_at, br.started_at) DESC, br.id DESC
                    ) AS row_num
                FROM benchmark_runs br
                JOIN puzzle_instances pi ON pi.id = br.puzzle_instance_id
                WHERE pi.puzzle_date = ? AND br.status = 'completed'
            )
            INSERT INTO leaderboard_daily (
                leaderboard_date, provider, model_id, average_score, solve_rate,
                puzzle_count, average_latency_ms, average_cost_usd
            )
            SELECT
                puzzle_date AS leaderboard_date,
                provider,
                model_id,
                AVG(normalized_score) AS average_score,
                AVG(CASE WHEN solve_status = 'solved' THEN 1.0 ELSE 0.0 END) AS solve_rate,
                COUNT(*) AS puzzle_count,
                AVG(latency_ms) AS average_latency_ms,
                AVG(cost_estimate_usd) AS average_cost_usd
            FROM latest_runs
            WHERE row_num = 1
            GROUP BY puzzle_date, provider, model_id
            """,
            (target_date.isoformat(),),
        )


def fetch_leaderboard_rows(target_date: date) -> list[sqlite3.Row]:
    with connect() as conn:
        rows = conn.execute(
            """
            WITH latest_runs AS (
                SELECT
                    br.id,
                    br.provider,
                    br.model_id,
                    br.normalized_score,
                    br.solve_status,
                    br.latency_ms,
                    br.cost_estimate_usd,
                    pi.puzzle_date,
                    pi.puzzle_key,
                    (
                        SELECT path
                        FROM artifacts artifact
                        WHERE artifact.run_id = br.id AND artifact.artifact_type = 'video'
                        ORDER BY artifact.id DESC
                        LIMIT 1
                    ) AS video_path,
                    ROW_NUMBER() OVER (
                        PARTITION BY pi.puzzle_date, pi.puzzle_key, br.provider, br.model_id
                        ORDER BY COALESCE(br.completed_at, br.started_at) DESC, br.id DESC
                    ) AS row_num
                FROM benchmark_runs br
                JOIN puzzle_instances pi ON pi.id = br.puzzle_instance_id
                WHERE pi.puzzle_date = ? AND br.status = 'completed'
            )
            SELECT
                puzzle_date AS leaderboard_date,
                provider,
                model_id,
                AVG(normalized_score) AS average_score,
                AVG(CASE WHEN solve_status = 'solved' THEN 1.0 ELSE 0.0 END) AS solve_rate,
                COUNT(*) AS puzzle_count,
                AVG(latency_ms) AS average_latency_ms,
                AVG(cost_estimate_usd) AS average_cost_usd,
                MAX(id) AS representative_run_id,
                MAX(COALESCE(video_path, '')) AS representative_video_path
            FROM latest_runs
            WHERE row_num = 1
            GROUP BY puzzle_date, provider, model_id
            ORDER BY average_score DESC, solve_rate DESC, average_latency_ms ASC
            """,
            (target_date.isoformat(),),
        ).fetchall()
    return rows


def fetch_recent_runs(limit: int = 50) -> list[sqlite3.Row]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT br.id, br.provider, br.model_id, br.status, br.solve_status,
                   br.normalized_score, br.started_at, br.completed_at, br.failure_category,
                   (
                       SELECT path
                       FROM artifacts artifact
                       WHERE artifact.run_id = br.id AND artifact.artifact_type = 'video'
                       ORDER BY artifact.id DESC
                       LIMIT 1
                   ) AS video_path,
                   pi.puzzle_key, pi.display_name, pi.puzzle_date
            FROM benchmark_runs br
            JOIN puzzle_instances pi ON pi.id = br.puzzle_instance_id
            ORDER BY br.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows


def fetch_run_detail(run_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        run_row = conn.execute(
            """
            SELECT br.*, pi.puzzle_key, pi.display_name, pi.puzzle_date, pi.source_url, pi.snapshot_json
            FROM benchmark_runs br
            JOIN puzzle_instances pi ON pi.id = br.puzzle_instance_id
            WHERE br.id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None
        step_rows = conn.execute(
            """
            SELECT step_index, action_kind, action_payload_json, rationale, observation_json, artifacts_json
            FROM attempt_steps
            WHERE run_id = ?
            ORDER BY step_index ASC
            """,
            (run_id,),
        ).fetchall()
        artifact_rows = conn.execute(
            "SELECT artifact_type, path, metadata_json FROM artifacts WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    return {
        "run": run_row,
        "steps": step_rows,
        "artifacts": artifact_rows,
    }
