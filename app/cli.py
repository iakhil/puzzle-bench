from __future__ import annotations

from datetime import date, datetime, timezone
import sys

try:
    from .db import init_db
    from .model_adapters import OpenAIWordleModelAdapter
    from .model_adapters import ScriptedModelAdapter
    from .model_adapters import ScriptedWordleModelAdapter
    from .puzzle_adapters import default_puzzle_adapters, demo_puzzle_adapters
    from .runner import BenchmarkRunner
    from .sandbox import LocalFixtureSandboxProvider, LocalPlaywrightSandboxProvider
    from .repository import recompute_daily_leaderboard
except ImportError:  # pragma: no cover - direct script execution fallback
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app.db import init_db
    from app.model_adapters import OpenAIWordleModelAdapter
    from app.model_adapters import ScriptedModelAdapter
    from app.model_adapters import ScriptedWordleModelAdapter
    from app.puzzle_adapters import default_puzzle_adapters, demo_puzzle_adapters
    from app.runner import BenchmarkRunner
    from app.sandbox import LocalFixtureSandboxProvider, LocalPlaywrightSandboxProvider
    from app.repository import recompute_daily_leaderboard


DEMO_MODELS = [
    ScriptedModelAdapter(provider="openai", model_id="gpt-4.1-mini"),
    ScriptedModelAdapter(provider="anthropic", model_id="claude-3-7-sonnet"),
    ScriptedModelAdapter(provider="google", model_id="gemini-2.5-pro"),
]

LIVE_MODELS = [
    ScriptedWordleModelAdapter(provider="openai", model_id="gpt-4.1-mini", guess_sequence=["crane", "adult", "plaid"]),
    ScriptedWordleModelAdapter(provider="anthropic", model_id="claude-3-7-sonnet", guess_sequence=["stare", "adieu", "float"]),
    ScriptedWordleModelAdapter(provider="google", model_id="gemini-2.5-pro", guess_sequence=["slate", "round", "plaid"]),
]


def _target_date_from_args(args: list[str]) -> date:
    if args:
        return date.fromisoformat(args[0])
    return datetime.now(timezone.utc).date()


def seed_demo(target_date: date) -> None:
    init_db()
    runner = BenchmarkRunner(LocalFixtureSandboxProvider())
    runner.run_daily_benchmark(target_date, demo_puzzle_adapters(), DEMO_MODELS)


def run_live_wordle(target_date: date) -> None:
    init_db()
    runner = BenchmarkRunner(LocalPlaywrightSandboxProvider())
    runner.run_daily_benchmark(target_date, default_puzzle_adapters(), LIVE_MODELS)


def run_live_wordle_openai(target_date: date) -> None:
    init_db()
    runner = BenchmarkRunner(LocalPlaywrightSandboxProvider())
    runner.run_daily_benchmark(target_date, default_puzzle_adapters(), [OpenAIWordleModelAdapter()])


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print(
            "Usage: python -m app.cli "
            "<seed-demo|run-daily-benchmark|run-live-wordle|run-live-wordle-openai|fetch-daily-puzzles|recompute-leaderboard> [YYYY-MM-DD]"
        )
        return 1

    command = args.pop(0)
    target_date = _target_date_from_args(args)
    init_db()

    if command == "seed-demo":
        seed_demo(target_date)
        return 0
    if command in {"run-daily-benchmark", "run-live-wordle"}:
        run_live_wordle(target_date)
        return 0
    if command == "run-live-wordle-openai":
        run_live_wordle_openai(target_date)
        return 0
    if command == "fetch-daily-puzzles":
        BenchmarkRunner(LocalFixtureSandboxProvider()).fetch_daily_puzzles(demo_puzzle_adapters(), target_date)
        return 0
    if command == "recompute-leaderboard":
        recompute_daily_leaderboard(target_date)
        return 0

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
