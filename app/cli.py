from __future__ import annotations

from datetime import date, datetime, timezone
import sys

from .db import init_db
from .model_adapters import ScriptedModelAdapter
from .puzzle_adapters import default_puzzle_adapters
from .runner import BenchmarkRunner
from .sandbox import LocalPlaywrightSandboxProvider
from .repository import recompute_daily_leaderboard


DEFAULT_MODELS = [
    ScriptedModelAdapter(provider="openai", model_id="gpt-4.1-mini"),
    ScriptedModelAdapter(provider="anthropic", model_id="claude-3-7-sonnet"),
    ScriptedModelAdapter(provider="google", model_id="gemini-2.5-pro"),
]


def _target_date_from_args(args: list[str]) -> date:
    if args:
        return date.fromisoformat(args[0])
    return datetime.now(timezone.utc).date()


def seed_demo(target_date: date) -> None:
    init_db()
    runner = BenchmarkRunner(LocalPlaywrightSandboxProvider())
    runner.run_daily_benchmark(target_date, default_puzzle_adapters(), DEFAULT_MODELS)


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print("Usage: python -m app.cli <seed-demo|run-daily-benchmark|fetch-daily-puzzles|recompute-leaderboard> [YYYY-MM-DD]")
        return 1

    command = args.pop(0)
    target_date = _target_date_from_args(args)
    init_db()

    if command in {"seed-demo", "run-daily-benchmark"}:
        seed_demo(target_date)
        return 0
    if command == "fetch-daily-puzzles":
        BenchmarkRunner(LocalPlaywrightSandboxProvider()).fetch_daily_puzzles(default_puzzle_adapters(), target_date)
        return 0
    if command == "recompute-leaderboard":
        recompute_daily_leaderboard(target_date)
        return 0

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
