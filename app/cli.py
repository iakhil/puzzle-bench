from __future__ import annotations

from datetime import date, datetime, timezone
import os
import sys

try:
    from .agentic_browser import run_agentic_wordle, run_agentic_wordle_anthropic, run_agentic_wordle_openai
    from .db import init_db
    from .model_adapters import OpenAIWordleModelAdapter
    from .model_adapters import ScriptedModelAdapter
    from .model_adapters import ScriptedWordleModelAdapter
    from .puzzle_adapters import default_puzzle_adapters, demo_puzzle_adapters
    from .runner import BenchmarkRunner
    from .sandbox import BrowserbaseSandboxProvider, LocalFixtureSandboxProvider, LocalPlaywrightSandboxProvider
    from .repository import recompute_daily_leaderboard
except ImportError:  # pragma: no cover - direct script execution fallback
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app.agentic_browser import run_agentic_wordle, run_agentic_wordle_anthropic, run_agentic_wordle_openai
    from app.db import init_db
    from app.model_adapters import OpenAIWordleModelAdapter
    from app.model_adapters import ScriptedModelAdapter
    from app.model_adapters import ScriptedWordleModelAdapter
    from app.puzzle_adapters import default_puzzle_adapters, demo_puzzle_adapters
    from app.runner import BenchmarkRunner
    from app.sandbox import BrowserbaseSandboxProvider, LocalFixtureSandboxProvider, LocalPlaywrightSandboxProvider
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


def _print_progress(event: str, payload: dict[str, object]) -> None:
    model_label = f"{payload.get('provider')}/{payload.get('model_id')}"
    puzzle_key = str(payload.get("puzzle_key", "unknown"))
    run_id = str(payload.get("run_id", "unknown"))
    if event == "run_started":
        print(f"[start] {model_label} on {puzzle_key} (run_id={run_id})")
        return
    if event == "step_completed":
        step_index = int(payload.get("step_index", 0)) + 1
        action_kind = payload.get("action_kind")
        print(f"[step {step_index}] {model_label} {action_kind} on {puzzle_key}")
        visible_text = str(payload.get("visible_text", "")).strip()
        if visible_text:
            print(visible_text)
        screenshot_path = payload.get("screenshot_path")
        if screenshot_path:
            print(f"  screenshot: {screenshot_path}")
        return
    if event == "run_completed":
        score = float(payload.get("normalized_score", 0.0))
        latency_ms = int(payload.get("latency_ms", 0))
        solve_status = payload.get("solve_status")
        failure_category = payload.get("failure_category")
        print(
            f"[done] {model_label} on {puzzle_key} "
            f"status={solve_status} score={score:.1f} latency_ms={latency_ms} run_id={run_id}"
        )
        if failure_category:
            print(f"  failure_category: {failure_category}")
        snapshot_path = payload.get("snapshot_path")
        trace_path = payload.get("trace_path")
        if snapshot_path:
            print(f"  snapshot: {snapshot_path}")
        if trace_path:
            print(f"  trace: {trace_path}")


def _print_agentic_progress(event: str, payload: dict[str, object]) -> None:
    provider = payload.get("provider")
    if event == "run_started":
        print(
            f"[start] {provider}/{payload.get('model_id')} agentic browser run "
            f"(run_id={payload.get('run_id')})"
        )
        print(f"  sandbox: {payload.get('sandbox_type')}")
        print(f"  artifacts: {payload.get('artifact_dir')}")
        return
    if event == "browser_started":
        print(f"[browser] opened {payload.get('current_url')} headless={payload.get('headless')}")
        replay_url = payload.get("replay_url")
        if replay_url:
            print(f"  replay: {replay_url}")
        return
    if event == "reasoning":
        print(f"[reasoning] {payload.get('summary')}")
        return
    if event == "turn_started":
        actions = payload.get("actions") or []
        print(f"[turn {payload.get('turn_index')}] model returned {len(actions)} action(s)")
        for index, action in enumerate(actions, start=1):
            print(f"  action {index}: {action}")
        return
    if event == "computer_action":
        print(f"[exec] {payload.get('action')}")
        return
    if event == "screenshot_captured":
        print(
            f"[screenshot] turn={payload.get('turn_index')} "
            f"url={payload.get('current_url')} path={payload.get('screenshot_path')}"
        )
        return
    if event == "run_completed":
        print(
            f"[done] {provider}/{payload.get('model_id')} final_url={payload.get('final_url')} "
            f"turns={payload.get('turn_count')}"
        )
        final_text = str(payload.get("final_text", "")).strip()
        if final_text:
            print(f"  final_text: {final_text}")
        print(f"  artifacts: {payload.get('artifact_dir')}")


def _print_results(results) -> None:
    if not results:
        print("No runs were created.")
        return
    print("Completed runs:")
    for result in results:
        print(
            f"- {result.provider}/{result.model_id} on {result.puzzle_key}: "
            f"status={result.solve_status} score={result.normalized_score:.1f} "
            f"latency_ms={result.latency_ms} run_id={result.run_id}"
        )
        if result.failure_category:
            print(f"  failure_category={result.failure_category}")
        print(f"  snapshot={result.snapshot_path}")
        print(f"  trace={result.trace_path}")


def _target_date_from_args(args: list[str]) -> date:
    if args:
        return date.fromisoformat(args[0])
    return datetime.now(timezone.utc).date()


def seed_demo(target_date: date) -> None:
    init_db()
    runner = BenchmarkRunner(LocalFixtureSandboxProvider(), progress_callback=_print_progress)
    results = runner.run_daily_benchmark(target_date, demo_puzzle_adapters(), DEMO_MODELS)
    _print_results(results)


def run_live_wordle(target_date: date) -> None:
    init_db()
    provider = BrowserbaseSandboxProvider() if (os.getenv("GAME_BENCH_BROWSER_PROVIDER") == "browserbase") else LocalPlaywrightSandboxProvider()
    runner = BenchmarkRunner(provider, progress_callback=_print_progress)
    results = runner.run_daily_benchmark(target_date, default_puzzle_adapters(), LIVE_MODELS)
    _print_results(results)


def run_live_wordle_openai(target_date: date) -> None:
    init_db()
    provider = BrowserbaseSandboxProvider() if (os.getenv("GAME_BENCH_BROWSER_PROVIDER") == "browserbase") else LocalPlaywrightSandboxProvider()
    runner = BenchmarkRunner(provider, progress_callback=_print_progress)
    results = runner.run_daily_benchmark(target_date, default_puzzle_adapters(), [OpenAIWordleModelAdapter()])
    _print_results(results)


def run_live_wordle_openai_agentic(target_date: date) -> None:
    init_db()
    result = run_agentic_wordle_openai(target_date=target_date, progress_callback=_print_agentic_progress)
    print(
        f"Completed agentic browser run: model={result.model_id} status={result.solve_status} "
        f"score={result.normalized_score:.1f} turns={result.turn_count} final_url={result.final_url}"
    )
    if result.final_text:
        print(f"Final summary: {result.final_text}")
    print(f"Run detail: /runs/{result.run_id}")
    if result.video_path:
        print(f"Video: {result.video_path}")
    print(f"Artifacts: {result.artifact_dir}")


def run_live_wordle_anthropic_agentic(target_date: date) -> None:
    init_db()
    result = run_agentic_wordle_anthropic(target_date=target_date, progress_callback=_print_agentic_progress)
    print(
        f"Completed agentic browser run: provider={result.provider} model={result.model_id} "
        f"status={result.solve_status} score={result.normalized_score:.1f} "
        f"turns={result.turn_count} final_url={result.final_url}"
    )
    if result.final_text:
        print(f"Final summary: {result.final_text}")
    print(f"Run detail: /runs/{result.run_id}")
    if result.video_path:
        print(f"Video: {result.video_path}")
    print(f"Artifacts: {result.artifact_dir}")


def run_live_wordle_agentic(target_date: date, provider: str = "openai", model_id: str | None = None) -> None:
    init_db()
    result = run_agentic_wordle(
        provider=provider,
        model_id=model_id,
        target_date=target_date,
        progress_callback=_print_agentic_progress,
    )
    print(
        f"Completed agentic browser run: provider={result.provider} model={result.model_id} "
        f"status={result.solve_status} score={result.normalized_score:.1f} "
        f"turns={result.turn_count} final_url={result.final_url}"
    )
    if result.final_text:
        print(f"Final summary: {result.final_text}")
    print(f"Run detail: /runs/{result.run_id}")
    if result.video_path:
        print(f"Video: {result.video_path}")
    print(f"Artifacts: {result.artifact_dir}")


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if not args:
        print(
            "Usage: python -m app.cli "
            "<seed-demo|run-daily-benchmark|run-live-wordle|run-live-wordle-openai|run-live-wordle-openai-agentic|run-live-wordle-claude-agentic|run-live-wordle-agentic|fetch-daily-puzzles|recompute-leaderboard> [provider] [YYYY-MM-DD]"
        )
        return 1

    command = args.pop(0)
    init_db()

    if command == "seed-demo":
        target_date = _target_date_from_args(args)
        seed_demo(target_date)
        return 0
    if command in {"run-daily-benchmark", "run-live-wordle"}:
        target_date = _target_date_from_args(args)
        run_live_wordle(target_date)
        return 0
    if command == "run-live-wordle-openai":
        target_date = _target_date_from_args(args)
        run_live_wordle_openai(target_date)
        return 0
    if command == "run-live-wordle-openai-agentic":
        target_date = _target_date_from_args(args)
        run_live_wordle_openai_agentic(target_date)
        return 0
    if command == "run-live-wordle-claude-agentic":
        target_date = _target_date_from_args(args)
        run_live_wordle_anthropic_agentic(target_date)
        return 0
    if command == "run-live-wordle-agentic":
        provider = args.pop(0) if args and "-" not in args[0] else "openai"
        target_date = _target_date_from_args(args)
        run_live_wordle_agentic(target_date, provider=provider)
        return 0
    if command == "fetch-daily-puzzles":
        target_date = _target_date_from_args(args)
        BenchmarkRunner(LocalFixtureSandboxProvider()).fetch_daily_puzzles(demo_puzzle_adapters(), target_date)
        return 0
    if command == "recompute-leaderboard":
        target_date = _target_date_from_args(args)
        recompute_daily_leaderboard(target_date)
        return 0

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
