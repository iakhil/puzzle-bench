from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import time
import uuid

from .config import get_settings
from .domain import ModelAdapter, PuzzleAdapter, RunBudget, RunContext, SandboxProvider
from .repository import (
    add_artifact,
    add_attempt_step,
    insert_run,
    recompute_daily_leaderboard,
    update_run_result,
    upsert_puzzle_instance,
)
from .sandbox import write_run_artifact


@dataclass(frozen=True)
class DailyRunResult:
    run_id: str
    model_id: str
    provider: str
    puzzle_key: str
    benchmark_date: date


class BenchmarkRunner:
    def __init__(self, sandbox_provider: SandboxProvider) -> None:
        self.sandbox_provider = sandbox_provider
        self.settings = get_settings()

    def fetch_daily_puzzles(self, adapters: list[PuzzleAdapter], target_date: date) -> None:
        for adapter in adapters:
            puzzle = adapter.fetch_puzzle(target_date)
            upsert_puzzle_instance(puzzle)

    def run_daily_benchmark(
        self,
        target_date: date,
        puzzle_adapters: list[PuzzleAdapter],
        model_adapters: list[ModelAdapter],
    ) -> list[DailyRunResult]:
        results: list[DailyRunResult] = []
        for puzzle_adapter in puzzle_adapters:
            puzzle = puzzle_adapter.fetch_puzzle(target_date)
            puzzle_instance_id = upsert_puzzle_instance(puzzle)
            for model_adapter in model_adapters:
                results.append(
                    self._run_once(
                        target_date=target_date,
                        puzzle_adapter=puzzle_adapter,
                        puzzle=puzzle,
                        puzzle_instance_id=puzzle_instance_id,
                        model_adapter=model_adapter,
                    )
                )
        recompute_daily_leaderboard(target_date)
        return results

    def _run_once(
        self,
        target_date: date,
        puzzle_adapter: PuzzleAdapter,
        puzzle,
        puzzle_instance_id: int,
        model_adapter: ModelAdapter,
    ) -> DailyRunResult:
        budget = RunBudget(
            max_steps=self.settings.default_budget_steps,
            max_seconds=self.settings.default_budget_seconds,
        )
        run_id = uuid.uuid4().hex
        started_at = datetime.now(timezone.utc)
        prompt_hash = self._prompt_hash(puzzle_adapter.instructions(puzzle), budget)
        insert_run(
            run_id=run_id,
            puzzle_instance_id=puzzle_instance_id,
            provider=model_adapter.provider,
            model_id=model_adapter.model_id,
            sandbox_type=self.sandbox_provider.provider_name,
            sandbox_session_id=run_id,
            prompt_config_hash=prompt_hash,
            started_at=started_at.isoformat(),
        )
        session = self.sandbox_provider.start_session(puzzle, run_id)
        run_context = RunContext(
            run_id=run_id,
            model_id=model_adapter.model_id,
            provider=model_adapter.provider,
            budget=budget,
            puzzle_instance=puzzle,
            started_at=started_at,
        )
        puzzle_adapter.setup_session(session, puzzle)
        trace: list[dict[str, object]] = []
        run_state = {"scripted_answer": puzzle.snapshot_data.get("answer")}
        time_start = time.perf_counter()
        try:
            for step_index in range(budget.max_steps):
                observation = session.observe(
                    instructions=puzzle_adapter.instructions(puzzle),
                    remaining_steps=budget.max_steps - step_index,
                )
                decision = model_adapter.next_action(observation, run_state)
                self._apply_action(session, decision.action.kind, decision.action.payload)
                if decision.action.kind == "submit_answer":
                    session.snapshot()["state"]["submitted_answer"] = decision.action.payload.get("answer")
                trace_step = {
                    "step_index": step_index,
                    "action_kind": decision.action.kind,
                    "action_payload": decision.action.payload,
                    "rationale": decision.rationale,
                }
                trace.append(trace_step)
                add_attempt_step(
                    run_id=run_id,
                    step_index=step_index,
                    action_kind=decision.action.kind,
                    action_payload=decision.action.payload,
                    rationale=decision.rationale,
                    observation=observation,
                    artifacts={},
                )
                if decision.action.kind == "finish" or puzzle_adapter.is_terminal(session, puzzle):
                    break
            scored_attempt = puzzle_adapter.score(session, puzzle, trace)
            latency_ms = int((time.perf_counter() - time_start) * 1000)
            token_usage = {"input_tokens": max(1, len(trace) * 25), "output_tokens": max(1, len(trace) * 10)}
            cost_estimate = round(token_usage["input_tokens"] * 0.000001 + token_usage["output_tokens"] * 0.000002, 6)
            snapshot_path = write_run_artifact(run_id, "snapshot", session.snapshot())
            trace_path = write_run_artifact(run_id, "trace", {"trace": trace, "run_context": run_context.run_id})
            add_artifact(run_id, "snapshot", snapshot_path, {"type": "session_snapshot"})
            add_artifact(run_id, "trace", trace_path, {"type": "action_trace"})
            update_run_result(
                run_id=run_id,
                status="completed",
                scored_attempt=scored_attempt,
                latency_ms=latency_ms,
                token_usage=token_usage,
                cost_estimate_usd=cost_estimate,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            session.close()
        return DailyRunResult(
            run_id=run_id,
            model_id=model_adapter.model_id,
            provider=model_adapter.provider,
            puzzle_key=puzzle_adapter.puzzle_key,
            benchmark_date=target_date,
        )

    def _apply_action(self, session, kind: str, payload: dict[str, object]) -> None:
        if kind == "click":
            session.click(str(payload["selector"]))
        elif kind == "type":
            session.type_text(str(payload["selector"]), str(payload["text"]))
        elif kind == "keypress":
            session.press_key(str(payload["key"]))
        elif kind == "scroll":
            session.scroll(int(payload["amount"]))
        elif kind == "navigate":
            session.navigate(str(payload["url"]))
        elif kind in {"submit_answer", "finish"}:
            return None
        else:
            raise ValueError(f"Unsupported action kind: {kind}")

    def _prompt_hash(self, instructions: str, budget: RunBudget) -> str:
        raw = json.dumps(
            {
                "instructions": instructions,
                "budget": {"max_steps": budget.max_steps, "max_seconds": budget.max_seconds},
                "sandbox": self.sandbox_provider.provider_name,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
