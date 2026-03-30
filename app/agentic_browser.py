from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from .config import get_settings
from .domain import Observation, PuzzleInstance, ScoredAttempt
from .repository import (
    add_artifact,
    add_attempt_step,
    insert_run,
    mark_run_failed,
    recompute_daily_leaderboard,
    update_run_result,
    upsert_puzzle_instance,
)
from .sandbox import _browserbase_replay_url, _create_browserbase_session


DEFAULT_WORDLE_URL = "https://www.nytimes.com/games/wordle/index.html"
DEFAULT_VIEWPORT_WIDTH = 1440
DEFAULT_VIEWPORT_HEIGHT = 1200
DEFAULT_OPENAI_COMPUTER_MODEL = "gpt-5.4"
DEFAULT_ANTHROPIC_COMPUTER_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_COMPUTER_BETA = "computer-use-2025-01-24"
ANTHROPIC_COMPUTER_TOOL_TYPE = "computer_20250124"


@dataclass(frozen=True)
class AgenticRunResult:
    run_id: str
    provider: str
    model_id: str
    final_url: str
    final_text: str
    turn_count: int
    artifact_dir: str
    solve_status: str
    normalized_score: float
    video_path: str | None


class PlaywrightComputerHarness:
    def __init__(
        self,
        run_id: str,
        start_url: str,
        headless: bool | None = None,
        keep_open_seconds: float | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    ) -> None:
        self.run_id = run_id
        self.start_url = start_url
        self.progress_callback = progress_callback
        self.headless = headless if headless is not None else os.getenv("GAME_BENCH_AGENTIC_HEADLESS", "0") != "0"
        default_keep_open = "15" if not self.headless else "0"
        self.keep_open_seconds = (
            keep_open_seconds
            if keep_open_seconds is not None
            else float(os.getenv("GAME_BENCH_AGENTIC_KEEP_OPEN_SECONDS", default_keep_open))
        )
        self.allowed_hosts = {"www.nytimes.com", "nytimes.com", "about:blank"}
        self.settings = get_settings()
        self.artifact_dir = self.settings.artifacts_root / run_id
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context = None
        self.page: Page | None = None
        self.video = None
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def start(self) -> None:
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            record_video_dir=str(self.artifact_dir),
            record_video_size={"width": self.viewport_width, "height": self.viewport_height},
        )
        self.page = self.context.new_page()
        self.video = self.page.video
        self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(1500)
        self._emit("browser_started", current_url=self.page.url, headless=self.headless)

    def capture_screenshot(self, label: str) -> tuple[str, str]:
        page = self._page()
        path = self.artifact_dir / f"{label}-{uuid.uuid4().hex[:8]}.png"
        image_bytes = page.screenshot(path=str(path), full_page=True)
        return str(path), base64.b64encode(image_bytes).decode("utf-8")

    def capture_tool_screenshot_base64(self) -> str:
        image_bytes = self._page().screenshot(full_page=False)
        return base64.b64encode(image_bytes).decode("utf-8")

    def execute_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        page = self._page()
        results: list[dict[str, Any]] = []
        for action in actions:
            self._ensure_allowed_page(page)
            self._emit("computer_action", action=action, current_url=page.url)
            result = self.apply_action(page, action)
            results.append(result)
            if action.get("type") not in {"wait", "screenshot"}:
                page.wait_for_timeout(700)
        return results

    @staticmethod
    def apply_action(page: Any, action: dict[str, Any]) -> dict[str, Any]:
        action_type = str(action.get("type"))
        if action_type == "click":
            page.mouse.click(action["x"], action["y"], button=action.get("button", "left"))
            return {"type": "text", "text": "OK"}
        if action_type == "double_click":
            page.mouse.dblclick(action["x"], action["y"], button=action.get("button", "left"))
            return {"type": "text", "text": "OK"}
        if action_type == "triple_click":
            page.mouse.click(action["x"], action["y"], button=action.get("button", "left"), click_count=3)
            return {"type": "text", "text": "OK"}
        if action_type == "scroll":
            page.mouse.move(action.get("x", 0), action.get("y", 0))
            page.mouse.wheel(
                action.get("scroll_x", action.get("scrollX", 0)),
                action.get("scroll_y", action.get("scrollY", 0)),
            )
            return {"type": "text", "text": "OK"}
        if action_type == "keypress":
            for key in action.get("keys", []):
                page.keyboard.press(_normalize_key(str(key)))
            return {"type": "text", "text": "OK"}
        if action_type == "keypress_combo":
            page.keyboard.press(_normalize_key_combo(str(action.get("combo", ""))))
            return {"type": "text", "text": "OK"}
        if action_type == "type":
            page.keyboard.type(action.get("text", ""))
            return {"type": "text", "text": "OK"}
        if action_type == "wait":
            time.sleep(float(action.get("seconds", 2)))
            return {"type": "text", "text": "OK"}
        if action_type == "move":
            page.mouse.move(action["x"], action["y"])
            return {"type": "text", "text": "OK"}
        if action_type == "drag":
            page.mouse.move(action["path"][0]["x"], action["path"][0]["y"])
            page.mouse.down(button=action.get("button", "left"))
            for point in action["path"][1:]:
                page.mouse.move(point["x"], point["y"])
            page.mouse.up(button=action.get("button", "left"))
            return {"type": "text", "text": "OK"}
        if action_type == "mouse_down":
            page.mouse.down(button=action.get("button", "left"))
            return {"type": "text", "text": "OK"}
        if action_type == "mouse_up":
            page.mouse.up(button=action.get("button", "left"))
            return {"type": "text", "text": "OK"}
        if action_type == "hold_key":
            key = _normalize_key(str(action.get("key", "")))
            duration = float(action.get("duration_seconds", action.get("duration", 1.0)))
            page.keyboard.down(key)
            time.sleep(duration)
            page.keyboard.up(key)
            return {"type": "text", "text": "OK"}
        if action_type == "screenshot":
            image_bytes = page.screenshot(full_page=False)
            return {
                "type": "image",
                "data": base64.b64encode(image_bytes).decode("utf-8"),
                "media_type": "image/png",
            }
        raise ValueError(f"Unsupported computer action: {action_type}")

    def current_url(self) -> str:
        return self._page().url

    def close(self) -> str | None:
        video_path: str | None = None
        try:
            if self.page is not None:
                try:
                    if self.keep_open_seconds > 0:
                        self.page.wait_for_timeout(int(self.keep_open_seconds * 1000))
                except KeyboardInterrupt:
                    pass
        finally:
            if self.context is not None:
                self.context.close()
            if self.video is not None:
                video_path = self.video.path()
            if self.browser is not None:
                self.browser.close()
            if self.playwright is not None:
                self.playwright.stop()
        return video_path

    def _page(self) -> Page:
        if self.page is None:
            raise RuntimeError("Browser page is not initialized.")
        return self.page

    def _emit(self, event: str, **payload: Any) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event, payload)

    def _ensure_allowed_page(self, page: Page) -> None:
        parsed = urlparse(page.url)
        host = parsed.hostname or page.url
        if host not in self.allowed_hosts:
            raise RuntimeError(f"Agent navigated to a non-allowlisted host: {page.url}")


class BrowserbaseComputerHarness(PlaywrightComputerHarness):
    def __init__(
        self,
        run_id: str,
        start_url: str,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    ) -> None:
        super().__init__(
            run_id=run_id,
            start_url=start_url,
            headless=True,
            keep_open_seconds=0,
            progress_callback=progress_callback,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        settings = get_settings()
        if not settings.browserbase_api_key or not settings.browserbase_project_id:
            raise RuntimeError("Browserbase credentials are not configured.")
        self.api_key = settings.browserbase_api_key
        self.project_id = settings.browserbase_project_id
        self.region = settings.browserbase_region
        self.session_id: str | None = None

    def start(self) -> None:
        session = _create_browserbase_session(
            api_key=self.api_key,
            project_id=self.project_id,
            region=self.region,
            run_id=self.run_id,
        )
        self.session_id = str(session["id"])
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(str(session["connectUrl"]))
        self.context = (
            self.browser.contexts[0]
            if self.browser.contexts
            else self.browser.new_context(viewport={"width": self.viewport_width, "height": self.viewport_height})
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_viewport_size({"width": self.viewport_width, "height": self.viewport_height})
        self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(1500)
        self._emit(
            "browser_started",
            current_url=self.page.url,
            headless=True,
            browserbase_session_id=self.session_id,
            replay_url=_browserbase_replay_url(self.session_id),
        )

    def close(self) -> str | None:
        try:
            return _browserbase_replay_url(self.session_id) if self.session_id else None
        finally:
            if self.browser is not None:
                self.browser.close()
            if self.playwright is not None:
                self.playwright.stop()


class OpenAIComputerUseClient:
    provider = "openai"
    response_artifact_type = "openai_response"

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or os.getenv("OPENAI_COMPUTER_MODEL", DEFAULT_OPENAI_COMPUTER_MODEL)
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.api_base = os.getenv("OPENAI_RESPONSES_API_BASE", "https://api.openai.com/v1/responses")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

    def create_initial_response(self, prompt: str, screenshot_base64: str | None = None) -> dict[str, Any]:
        return self._request(
            {
                "model": self.model_id,
                "tools": [{"type": "computer"}],
                "reasoning": {"summary": "concise"},
                "input": prompt,
            }
        )

    def extract_pending_call(self, response: dict[str, Any]) -> dict[str, Any] | None:
        computer_call = extract_computer_call(response)
        if computer_call is None:
            return None
        return {
            "call_id": computer_call["call_id"],
            "actions": list(computer_call.get("actions", [])),
            "pending_safety_checks": list(computer_call.get("pending_safety_checks") or []),
        }

    def continue_after_actions(
        self,
        response: dict[str, Any],
        pending_call: dict[str, Any],
        action_results: list[dict[str, Any]],
        screenshot_base64: str,
    ) -> dict[str, Any]:
        return self._request(
            {
                "model": self.model_id,
                "tools": [{"type": "computer"}],
                "previous_response_id": response["id"],
                "input": [
                    {
                        "type": "computer_call_output",
                        "call_id": pending_call["call_id"],
                        "output": {
                            "type": "computer_screenshot",
                            "image_url": f"data:image/png;base64,{screenshot_base64}",
                            "detail": "original",
                        },
                    }
                ],
            }
        )

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.api_base,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc


class AnthropicComputerUseClient:
    provider = "anthropic"
    response_artifact_type = "anthropic_response"

    def __init__(self, model_id: str | None = None, display_width_px: int = 1024, display_height_px: int = 768) -> None:
        self.model_id = model_id or os.getenv("ANTHROPIC_COMPUTER_MODEL", DEFAULT_ANTHROPIC_COMPUTER_MODEL)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.api_base = os.getenv("ANTHROPIC_MESSAGES_API_BASE", "https://api.anthropic.com/v1/messages")
        self.display_width_px = display_width_px
        self.display_height_px = display_height_px
        self.messages: list[dict[str, Any]] = []
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    def create_initial_response(self, prompt: str, screenshot_base64: str | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if screenshot_base64:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_base64,
                    },
                }
            )
        self.messages = [{"role": "user", "content": content}]
        return self._request()

    def extract_pending_call(self, response: dict[str, Any]) -> dict[str, Any] | None:
        tool_uses = extract_anthropic_tool_uses(response)
        if not tool_uses:
            return None
        return {
            "tool_uses": tool_uses,
            "actions": [_normalize_anthropic_tool_use(tool_use.get("input", {})) for tool_use in tool_uses],
        }

    def continue_after_actions(
        self,
        response: dict[str, Any],
        pending_call: dict[str, Any],
        action_results: list[dict[str, Any]],
        screenshot_base64: str,
    ) -> dict[str, Any]:
        self.messages.append({"role": "assistant", "content": response.get("content", [])})
        tool_results: list[dict[str, Any]] = []
        for tool_use, result in zip(pending_call["tool_uses"], action_results):
            tool_result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tool_use["id"],
                "content": _anthropic_tool_result_content(result),
            }
            if result.get("is_error"):
                tool_result["is_error"] = True
            tool_results.append(tool_result)
        self.messages.append({"role": "user", "content": tool_results})
        return self._request()

    def _request(self) -> dict[str, Any]:
        payload = {
            "model": self.model_id,
            "max_tokens": 4096,
            "tools": [
                {
                    "type": ANTHROPIC_COMPUTER_TOOL_TYPE,
                    "name": "computer",
                    "display_width_px": self.display_width_px,
                    "display_height_px": self.display_height_px,
                    "display_number": 1,
                }
            ],
            "messages": self.messages,
        }
        request = Request(
            self.api_base,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "anthropic-beta": ANTHROPIC_COMPUTER_BETA,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Anthropic API request failed: {exc.reason}") from exc


def run_agentic_wordle(
    provider: str = "openai",
    model_id: str | None = None,
    target_date: date | None = None,
    target_url: str = DEFAULT_WORDLE_URL,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> AgenticRunResult:
    run_id = uuid.uuid4().hex
    provider_name = provider.lower().strip()
    max_turns = int(os.getenv("GAME_BENCH_AGENTIC_MAX_TURNS", "30"))
    benchmark_date = target_date or datetime.now(timezone.utc).date()
    viewport_width, viewport_height = (
        _anthropic_display_dimensions(DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)
        if provider_name == "anthropic"
        else (DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)
    )
    settings = get_settings()
    if settings.browser_provider == "browserbase":
        harness = BrowserbaseComputerHarness(
            run_id=run_id,
            start_url=target_url,
            progress_callback=progress_callback,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        sandbox_type = "browserbase-agentic"
    else:
        harness = PlaywrightComputerHarness(
            run_id=run_id,
            start_url=target_url,
            progress_callback=progress_callback,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        sandbox_type = "local-playwright-agentic"
    client = _build_computer_use_client(
        provider_name,
        model_id,
        display_width_px=viewport_width,
        display_height_px=viewport_height,
    )
    puzzle = PuzzleInstance(
        puzzle_key="wordle",
        date=benchmark_date,
        display_name="NYT Wordle Agentic",
        source_url=target_url,
        snapshot_data={"source": "live-nyt-agentic", "visible_text": "Guess the Wordle in 6 tries."},
    )
    puzzle_instance_id = upsert_puzzle_instance(puzzle)
    started_at = datetime.now(timezone.utc)
    prompt_hash = hashlib.sha256(
        f"{client.provider}:{client.model_id}:{target_url}:agentic-wordle".encode("utf-8")
    ).hexdigest()
    insert_run(
        run_id=run_id,
        puzzle_instance_id=puzzle_instance_id,
        provider=client.provider,
        model_id=client.model_id,
        sandbox_type=sandbox_type,
        sandbox_session_id=run_id,
        prompt_config_hash=prompt_hash,
        started_at=started_at.isoformat(),
    )
    harness.start()
    response: dict[str, Any] = {}
    final_text = ""
    turn_count = 0
    final_url = target_url
    scored_attempt: ScoredAttempt | None = None
    video_path: str | None = None
    try:
        screenshot_path, _ = harness.capture_screenshot("initial")
        prompt = _build_agentic_prompt(target_url, screenshot_path)
        if progress_callback is not None:
            progress_callback(
                "run_started",
                {
                    "run_id": run_id,
                    "provider": client.provider,
                    "model_id": client.model_id,
                    "artifact_dir": str(harness.artifact_dir),
                    "sandbox_type": sandbox_type,
                },
            )
        response = client.create_initial_response(prompt, screenshot_base64=harness.capture_tool_screenshot_base64())
        response_path = _write_json_artifact(harness.artifact_dir, "response-initial", response)
        add_artifact(run_id, "response", response_path, {"type": client.response_artifact_type})

        while turn_count < max_turns:
            reasoning_summary = extract_reasoning_summary(response)
            if reasoning_summary and progress_callback is not None:
                progress_callback("reasoning", {"provider": client.provider, "turn_index": turn_count, "summary": reasoning_summary})

            pending_call = client.extract_pending_call(response)
            if pending_call is None:
                final_text = extract_output_text(response)
                if progress_callback is not None:
                    progress_callback(
                        "run_completed",
                        {
                            "run_id": run_id,
                            "provider": client.provider,
                            "model_id": client.model_id,
                            "turn_count": turn_count,
                            "final_url": harness.current_url(),
                            "final_text": final_text,
                            "artifact_dir": str(harness.artifact_dir),
                        },
                    )
                break

            pending_safety_checks = pending_call.get("pending_safety_checks") or []
            if pending_safety_checks:
                raise RuntimeError(
                    f"OpenAI computer tool returned pending safety checks: {json.dumps(pending_safety_checks)}"
                )

            actions = list(pending_call.get("actions", []))
            if progress_callback is not None:
                progress_callback(
                    "turn_started",
                    {"provider": client.provider, "turn_index": turn_count + 1, "actions": actions},
                )
            action_results = harness.execute_actions(actions)
            screenshot_path, _ = harness.capture_screenshot(f"turn-{turn_count + 1}")
            observation = _capture_observation(harness._page(), screenshot_path, turn_count + 1, max_turns)
            rationale = reasoning_summary or f"Executing {client.provider} computer-use actions."
            add_attempt_step(
                run_id=run_id,
                step_index=turn_count,
                action_kind="computer_actions",
                action_payload={"actions": actions, "provider": client.provider},
                rationale=rationale,
                observation=observation,
                artifacts={"screenshot_path": screenshot_path},
            )
            add_artifact(
                run_id,
                "screenshot",
                screenshot_path,
                {"type": "observation_screenshot", "step_index": turn_count},
            )
            if progress_callback is not None:
                progress_callback(
                    "screenshot_captured",
                    {
                        "provider": client.provider,
                        "turn_index": turn_count + 1,
                        "screenshot_path": screenshot_path,
                        "current_url": harness.current_url(),
                    },
                )
            response = client.continue_after_actions(
                response,
                pending_call,
                action_results,
                screenshot_base64=harness.capture_tool_screenshot_base64(),
            )
            response_path = _write_json_artifact(harness.artifact_dir, f"response-turn-{turn_count + 1}", response)
            add_artifact(
                run_id,
                "response",
                response_path,
                {"type": client.response_artifact_type, "step_index": turn_count},
            )
            turn_count += 1
        else:
            raise RuntimeError(f"Agentic run exceeded the configured turn limit ({max_turns}).")

        final_url = harness.current_url()
        final_text = extract_output_text(response)
        scored_attempt = _score_wordle_page(harness._page())
        latency_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        token_usage = {"input_tokens": max(1, turn_count * 1200), "output_tokens": max(1, turn_count * 200)}
        cost_estimate = 0.0
        trace_path = _write_json_artifact(
            harness.artifact_dir,
            "trace",
            {
                "provider": client.provider,
                "turn_count": turn_count,
                "final_text": final_text,
                "model_id": client.model_id,
            },
        )
        add_artifact(run_id, "trace", trace_path, {"type": "agentic_trace"})
        update_run_result(
            run_id=run_id,
            status="completed",
            scored_attempt=scored_attempt,
            latency_ms=latency_ms,
            token_usage=token_usage,
            cost_estimate_usd=cost_estimate,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        mark_run_failed(
            run_id=run_id,
            failure_category="agentic_runtime_error",
            completed_at=datetime.now(timezone.utc).isoformat(),
            raw_metrics={"error": str(exc)},
        )
        raise
    finally:
        video_path = harness.close()
        if video_path:
            artifact_kind = "browserbase_replay" if video_path.startswith("https://") else "playwright_video"
            add_artifact(run_id, "video", video_path, {"type": artifact_kind})
    recompute_daily_leaderboard(benchmark_date)
    return AgenticRunResult(
        run_id=run_id,
        provider=client.provider,
        model_id=client.model_id,
        final_url=final_url,
        final_text=final_text,
        turn_count=turn_count,
        artifact_dir=str(harness.artifact_dir),
        solve_status=scored_attempt.solve_status if scored_attempt else "failed",
        normalized_score=scored_attempt.normalized_score if scored_attempt else 0.0,
        video_path=video_path,
    )


def run_agentic_wordle_openai(
    target_date: date | None = None,
    target_url: str = DEFAULT_WORDLE_URL,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> AgenticRunResult:
    return run_agentic_wordle(
        provider="openai",
        target_date=target_date,
        target_url=target_url,
        progress_callback=progress_callback,
    )


def run_agentic_wordle_anthropic(
    target_date: date | None = None,
    target_url: str = DEFAULT_WORDLE_URL,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> AgenticRunResult:
    return run_agentic_wordle(
        provider="anthropic",
        target_date=target_date,
        target_url=target_url,
        progress_callback=progress_callback,
    )


def extract_computer_call(response: dict[str, Any]) -> dict[str, Any] | None:
    for item in response.get("output", []):
        if item.get("type") == "computer_call":
            return item
    return None


def extract_anthropic_tool_uses(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in response.get("content", [])
        if item.get("type") == "tool_use" and item.get("name") == "computer"
    ]


def extract_reasoning_summary(response: dict[str, Any]) -> str:
    if "output" in response:
        parts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "reasoning":
                continue
            for summary_item in item.get("summary", []):
                text = summary_item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return " ".join(parts)

    parts = []
    for item in response.get("content", []):
        if item.get("type") not in {"thinking", "redacted_thinking"}:
            continue
        text = item.get("thinking") or item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts)


def extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    if "output" in response:
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    parts: list[str] = []
    for item in response.get("content", []):
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


def _build_computer_use_client(
    provider: str,
    model_id: str | None,
    display_width_px: int,
    display_height_px: int,
) -> OpenAIComputerUseClient | AnthropicComputerUseClient:
    normalized = provider.lower().strip()
    if normalized == "openai":
        return OpenAIComputerUseClient(model_id=model_id)
    if normalized == "anthropic":
        return AnthropicComputerUseClient(
            model_id=model_id,
            display_width_px=display_width_px,
            display_height_px=display_height_px,
        )
    raise ValueError(f"Unsupported computer-use provider: {provider}")


def _build_agentic_prompt(target_url: str, screenshot_path: str) -> str:
    return (
        "You are controlling a browser that is already open to the New York Times Wordle page. "
        "Use the computer tool to play the game yourself. Close modals if needed, observe tile feedback visually from screenshots, "
        "and adapt each next guess accordingly. Prefer physical keyboard-style input for Wordle: use keyboard actions for letters, "
        "`ENTER`, and `BACKSPACE` instead of clicking the on-screen keyboard, because coordinate clicks on letter keys are brittle. "
        "Only use mouse clicks to dismiss popovers, focus the game if typing does not work, or interact with non-keyboard UI. "
        "Submit exactly one guess at a time: type five letters, press ENTER, then wait for the tile flip animation before deciding again. "
        "Do not log in, subscribe, or leave the Wordle page. Stop when the puzzle is complete and then provide a short final summary "
        "that states whether you solved it and in how many guesses. The current page URL is "
        f"{target_url}. The first screenshot artifact is saved at {screenshot_path}."
    )


def _anthropic_display_dimensions(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1568.0 / max(width, height), math.sqrt(1_150_000.0 / float(width * height)))
    return max(1, int(width * scale)), max(1, int(height * scale))


def _anthropic_tool_result_content(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("type") == "image":
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.get("media_type", "image/png"),
                    "data": result["data"],
                },
            }
        ]
    return [{"type": "text", "text": str(result.get("text", "OK"))}]


def _normalize_anthropic_tool_use(tool_input: dict[str, Any]) -> dict[str, Any]:
    action = str(tool_input.get("action", "")).strip().lower()
    if action == "screenshot":
        return {"type": "screenshot"}
    if action in {"left_click", "right_click", "middle_click"}:
        coordinate = tool_input.get("coordinate", [0, 0])
        button = action.replace("_click", "")
        return {"type": "click", "x": int(coordinate[0]), "y": int(coordinate[1]), "button": button}
    if action == "double_click":
        coordinate = tool_input.get("coordinate", [0, 0])
        return {"type": "double_click", "x": int(coordinate[0]), "y": int(coordinate[1]), "button": "left"}
    if action == "triple_click":
        coordinate = tool_input.get("coordinate", [0, 0])
        return {"type": "triple_click", "x": int(coordinate[0]), "y": int(coordinate[1]), "button": "left"}
    if action == "mouse_move":
        coordinate = tool_input.get("coordinate", [0, 0])
        return {"type": "move", "x": int(coordinate[0]), "y": int(coordinate[1])}
    if action == "type":
        return {"type": "type", "text": str(tool_input.get("text", ""))}
    if action == "key":
        return {"type": "keypress_combo", "combo": str(tool_input.get("text", ""))}
    if action == "hold_key":
        return {
            "type": "hold_key",
            "key": str(tool_input.get("text", "")),
            "duration_seconds": float(tool_input.get("duration", tool_input.get("duration_seconds", 1.0))),
        }
    if action == "scroll":
        amount = int(tool_input.get("scroll_amount", tool_input.get("amount", 0)))
        direction = str(tool_input.get("scroll_direction", tool_input.get("direction", "down"))).lower()
        coordinate = tool_input.get("coordinate", [0, 0])
        scroll_x = 0
        scroll_y = 0
        if direction == "up":
            scroll_y = -amount
        elif direction == "down":
            scroll_y = amount
        elif direction == "left":
            scroll_x = -amount
        elif direction == "right":
            scroll_x = amount
        return {
            "type": "scroll",
            "x": int(coordinate[0]),
            "y": int(coordinate[1]),
            "scroll_x": scroll_x,
            "scroll_y": scroll_y,
        }
    if action == "left_click_drag":
        start = tool_input.get("start_coordinate", tool_input.get("coordinate", [0, 0]))
        end = tool_input.get("end_coordinate", tool_input.get("destination_coordinate", start))
        return {
            "type": "drag",
            "button": "left",
            "path": [
                {"x": int(start[0]), "y": int(start[1])},
                {"x": int(end[0]), "y": int(end[1])},
            ],
        }
    if action == "left_mouse_down":
        return {"type": "mouse_down", "button": "left"}
    if action == "left_mouse_up":
        return {"type": "mouse_up", "button": "left"}
    if action == "wait":
        return {"type": "wait", "seconds": float(tool_input.get("duration", tool_input.get("seconds", 1.0)))}
    raise ValueError(f"Unsupported Anthropic computer-use action: {action}")


def _write_json_artifact(artifact_dir: Path, stem: str, payload: dict[str, Any]) -> str:
    path = artifact_dir / f"{stem}-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path)


def _capture_observation(page: Page, screenshot_path: str, step_index: int, max_turns: int) -> Observation:
    wordle_state = _extract_wordle_state_from_page(page)
    return Observation(
        current_url=page.url,
        title=page.title(),
        visible_text=_summarize_wordle_rows(wordle_state["rows"]),
        interactables=[],
        screenshot_path=screenshot_path,
        instructions="Agentic computer-use run",
        remaining_steps=max(0, max_turns - step_index),
        metadata={"wordle": wordle_state},
    )


def _score_wordle_page(page: Page) -> ScoredAttempt:
    wordle_state = _extract_wordle_state_from_page(page)
    guesses_used = wordle_state["submitted_rows"]
    if wordle_state["is_solved"]:
        score = max(100.0 - (guesses_used - 1) * 10.0, 50.0)
        status = "solved"
        failure_category = None
    else:
        score = 0.0
        status = "failed"
        failure_category = "max_guesses_exhausted" if wordle_state["is_failed"] else "unfinished"
    return ScoredAttempt(
        solve_status=status,
        normalized_score=score,
        raw_metrics={"submitted_rows": guesses_used, "rows": wordle_state["rows"]},
        failure_category=failure_category,
    )


def _extract_wordle_state_from_page(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const rows = Array.from(document.querySelectorAll('[role="group"][aria-label^="Row "]')).map((row, rowIndex) => {
            const tiles = Array.from(row.querySelectorAll('[data-testid="tile"]')).map((tile, tileIndex) => ({
              index: tileIndex + 1,
              label: tile.getAttribute('aria-label'),
              state: tile.getAttribute('data-state'),
              text: (tile.textContent || '').trim().toLowerCase(),
            }));
            const guess = tiles.map((tile) => tile.text).join('');
            const submitted = tiles.every((tile) => tile.state && tile.state !== 'empty' && tile.state !== 'tbd');
            return {
              row: rowIndex + 1,
              guess,
              submitted,
              tiles,
            };
          });
          const submittedRows = rows.filter((row) => row.submitted).length;
          const solvedRow = rows.find((row) => row.submitted && row.tiles.every((tile) => tile.state === 'correct'));
          return {
            rows,
            submitted_rows: submittedRows,
            is_solved: !!solvedRow,
            is_failed: submittedRows >= 6 && !solvedRow,
          };
        }
        """
    )


def _summarize_wordle_rows(rows: list[dict[str, Any]]) -> str:
    summaries: list[str] = []
    for row in rows:
        if row["guess"]:
            feedback = ",".join(tile["state"] for tile in row["tiles"])
            summaries.append(f"Row {row['row']}: {row['guess']} [{feedback}]")
        else:
            summaries.append(f"Row {row['row']}: empty")
    return "\n".join(summaries)


def _normalize_key(key: str) -> str:
    normalized = key.strip()
    aliases = {
        "SPACE": " ",
        "ENTER": "Enter",
        "RETURN": "Enter",
        "ESC": "Escape",
        "ESCAPE": "Escape",
        "TAB": "Tab",
        "BACKSPACE": "Backspace",
        "DELETE": "Delete",
        "UP": "ArrowUp",
        "DOWN": "ArrowDown",
        "LEFT": "ArrowLeft",
        "RIGHT": "ArrowRight",
        "CTRL": "Control",
        "CONTROL": "Control",
        "CMD": "Meta",
        "COMMAND": "Meta",
        "ALT": "Alt",
        "OPTION": "Alt",
        "SHIFT": "Shift",
    }
    return aliases.get(normalized.upper(), normalized)


def _normalize_key_combo(combo: str) -> str:
    parts = [part.strip() for part in combo.split("+") if part.strip()]
    if not parts:
        return combo
    return "+".join(_normalize_key(part) for part in parts)
