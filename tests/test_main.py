from __future__ import annotations

import os
from pathlib import Path
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import agentic_run_lock, app, artifact_url


class MainTests(unittest.TestCase):
    def test_artifact_url_supports_local_and_remote_paths(self) -> None:
        settings = get_settings()
        local_path = str(settings.artifacts_root / "run-1" / "video.webm")
        self.assertEqual(artifact_url(local_path), "/artifacts/run-1/video.webm")
        self.assertEqual(artifact_url("https://www.browserbase.com/sessions/abc"), "https://www.browserbase.com/sessions/abc")
        self.assertIsNone(artifact_url("/tmp/outside-artifact"))

    def test_settings_support_data_root_and_artifacts_root(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GAME_BENCH_DATA_ROOT": "/tmp/game-bench-data",
                "GAME_BENCH_DB_PATH": "/tmp/game-bench-data/prod.db",
                "GAME_BENCH_ARTIFACTS_ROOT": "/tmp/game-bench-data/replays",
            },
            clear=False,
        ):
            settings = get_settings()
        self.assertEqual(settings.db_path, Path("/tmp/game-bench-data/prod.db"))
        self.assertEqual(settings.artifacts_root, Path("/tmp/game-bench-data/replays"))

    def test_internal_run_requires_admin_token(self) -> None:
        with patch("app.main.settings", replace(get_settings(), admin_token="secret-token")):
            client = TestClient(app)
            response = client.post("/internal/runs/wordle-agentic", json={})
        self.assertEqual(response.status_code, 401)

    def test_internal_run_respects_single_run_lock(self) -> None:
        acquired = agentic_run_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with patch("app.main.settings", replace(get_settings(), admin_token="secret-token")):
                client = TestClient(app)
                response = client.post(
                    "/internal/runs/wordle-agentic",
                    json={},
                    headers={"Authorization": "Bearer secret-token"},
                )
            self.assertEqual(response.status_code, 409)
        finally:
            agentic_run_lock.release()


if __name__ == "__main__":
    unittest.main()
