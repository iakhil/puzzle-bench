from __future__ import annotations

from datetime import date
import unittest

from app.db import init_db, reset_db
from app.model_adapters import ScriptedModelAdapter
from app.puzzle_adapters import FixtureWordleAdapter
from app.repository import add_artifact, fetch_leaderboard_rows, fetch_recent_runs, recompute_daily_leaderboard
from app.runner import BenchmarkRunner
from app.sandbox import LocalFixtureSandboxProvider


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_db()
        init_db()

    def test_daily_benchmark_creates_leaderboard(self) -> None:
        runner = BenchmarkRunner(LocalFixtureSandboxProvider())
        results = runner.run_daily_benchmark(
            target_date=date(2026, 3, 27),
            puzzle_adapters=[FixtureWordleAdapter()],
            model_adapters=[ScriptedModelAdapter(provider="openai", model_id="gpt-4.1-mini")],
        )

        self.assertEqual(len(results), 1)
        add_artifact(results[0].run_id, "video", "/tmp/fixture-video.webm", {"type": "playwright_video"})
        recompute_daily_leaderboard(date(2026, 3, 27))
        leaderboard = fetch_leaderboard_rows(date(2026, 3, 27))
        self.assertEqual(len(leaderboard), 1)
        self.assertEqual(leaderboard[0]["average_score"], 100.0)
        self.assertEqual(leaderboard[0]["representative_run_id"], results[0].run_id)
        self.assertEqual(leaderboard[0]["representative_video_path"], "/tmp/fixture-video.webm")

        recent_runs = fetch_recent_runs()
        self.assertEqual(len(recent_runs), 1)
        self.assertEqual(recent_runs[0]["solve_status"], "solved")
        self.assertEqual(recent_runs[0]["video_path"], "/tmp/fixture-video.webm")


if __name__ == "__main__":
    unittest.main()
