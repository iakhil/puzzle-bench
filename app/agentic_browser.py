from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import json
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from .config import get_settings


DEFAULT_WORDLE_URL = "https://www.nytimes.com/games/wordle/index.html"


@dataclass(frozen=True)
class AgenticRunResult:
    run_id: str
    model_id: str
    final_url: str
    final_text: str
    turn_count: int
    artifact_dir: str


class PlaywrightComputerHarness:
    def __init__(
        self,
        run_id: str,
        start_url: str,
        headless: bool | None = None,
        keep_open_seconds: float | None = None,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
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
        self.artifact_dir = self.settings.base_dir / "data" / "artifacts" / run_id
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    def start(self) -> None:
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 1200})
        self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(1500)
        self._emit("browser_started", current_url=self.page.url, headless=self.headless)

    def capture_screenshot(self, label: str) -> tuple[str, str]:
        page = self._page()
        path = self.artifact_dir / f"{label}-{uuid.uuid4().hex[:8]}.png"
        image_bytes = page.screenshot(path=str(path), full_page=True)
        return str(path), base64.b64encode(image_bytes).decode("utf-8")

    def execute_actions(self, actions: list[dict[str, Any]]) -> None:
        page = self._page()
        for action in actions:
            self._ensure_allowed_page(page)
            self._emit("computer_action", action=action, current_url=page.url)
            self.apply_action(page, action)
            if action.get("type") not in {"wait", "screenshot"}:
                page.wait_for_timeout(700)

    @staticmethod
    def apply_action(page: Any, action: dict[str, Any]) -> None:
        action_type = str(action.get("type"))
        if action_type == "click":
            page.mouse.click(action["x"], action["y"], button=action.get("button", "left"))
            return
        if action_type == "double_click":
            page.mouse.dblclick(action["x"], action["y"], button=action.get("button", "left"))
            return
        if action_type == "scroll":
            page.mouse.move(action.get("x", 0), action.get("y", 0))
            page.mouse.wheel(action.get("scroll_x", action.get("scrollX", 0)), action.get("scroll_y", action.get("scrollY", 0)))
            return
        if action_type == "keypress":
            for key in action.get("keys", []):
                page.keyboard.press(_normalize_key(str(key)))
            return
        if action_type == "type":
            page.keyboard.type(action.get("text", ""))
            return
        if action_type == "wait":
            time.sleep(2)
            return
        if action_type == "move":
            page.mouse.move(action["x"], action["y"])
            return
        if action_type == "drag":
            page.mouse.move(action["path"][0]["x"], action["path"][0]["y"])
            page.mouse.down()
            for point in action["path"][1:]:
                page.mouse.move(point["x"], point["y"])
            page.mouse.up()
            return
        if action_type == "screenshot":
            return
        raise ValueError(f"Unsupported computer action: {action_type}")

    def current_url(self) -> str:
        return self._page().url

    def close(self) -> None:
        try:
            if self.page is not None and self.keep_open_seconds > 0:
                self.page.wait_for_timeout(int(self.keep_open_seconds * 1000))
        finally:
            if self.browser is not None:
                self.browser.close()
            if self.playwright is not None:
                self.playwright.stop()

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


class OpenAIComputerUseClient:
    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or os.getenv("OPENAI_COMPUTER_MODEL", "gpt-5.4")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.api_base = os.getenv("OPENAI_RESPONSES_API_BASE", "https://api.openai.com/v1/responses")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

    def create_initial_response(self, prompt: str) -> dict[str, Any]:
        return self._request(
            {
                "model": self.model_id,
                "tools": [{"type": "computer"}],
                "reasoning": {"summary": "concise"},
                "input": prompt,
            }
        )

    def continue_with_screenshot(
        self,
        previous_response_id: str,
        call_id: str,
        screenshot_base64: str,
    ) -> dict[str, Any]:
        return self._request(
            {
                "model": self.model_id,
                "tools": [{"type": "computer"}],
                "previous_response_id": previous_response_id,
                "input": [
                    {
                        "type": "computer_call_output",
                        "call_id": call_id,
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


def run_agentic_wordle_openai(
    target_url: str = DEFAULT_WORDLE_URL,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> AgenticRunResult:
    run_id = uuid.uuid4().hex
    max_turns = int(os.getenv("GAME_BENCH_AGENTIC_MAX_TURNS", "30"))
    harness = PlaywrightComputerHarness(run_id=run_id, start_url=target_url, progress_callback=progress_callback)
    client = OpenAIComputerUseClient()
    harness.start()
    try:
        screenshot_path, screenshot_base64 = harness.capture_screenshot("initial")
        prompt = (
            "You are controlling a browser that is already open to the New York Times Wordle page. "
            "Use the computer tool to play the game yourself. Close modals if needed, observe tile feedback visually from screenshots, "
            "and adapt each next guess accordingly. Prefer physical keyboard-style input for Wordle: use `keypress` actions for letters, "
            "`ENTER`, and `BACKSPACE` instead of clicking the on-screen keyboard, because coordinate clicks on letter keys are brittle. "
            "Only use mouse clicks to dismiss popovers, focus the game if typing does not work, or interact with non-keyboard UI. "
            "Submit exactly one guess at a time: type five letters, press ENTER, then wait for the tile flip animation before deciding again. "
            "Do not log in, subscribe, or leave the Wordle page. Stop when the puzzle is complete and then provide a short final summary "
            "that states whether you solved it and in how many guesses. The current page URL is "
            f"{target_url}. The first screenshot artifact is saved at {screenshot_path}."
        )
        if progress_callback is not None:
            progress_callback("run_started", {"run_id": run_id, "model_id": client.model_id, "artifact_dir": str(harness.artifact_dir)})
        response = client.create_initial_response(prompt)
        _write_json_artifact(harness.artifact_dir, "response-initial", response)
        turn_count = 0

        while turn_count < max_turns:
            reasoning_summary = extract_reasoning_summary(response)
            if reasoning_summary and progress_callback is not None:
                progress_callback("reasoning", {"turn_index": turn_count, "summary": reasoning_summary})
            computer_call = extract_computer_call(response)
            if computer_call is None:
                final_text = extract_output_text(response)
                if progress_callback is not None:
                    progress_callback(
                        "run_completed",
                        {
                            "run_id": run_id,
                            "model_id": client.model_id,
                            "turn_count": turn_count,
                            "final_url": harness.current_url(),
                            "final_text": final_text,
                            "artifact_dir": str(harness.artifact_dir),
                        },
                    )
                return AgenticRunResult(
                    run_id=run_id,
                    model_id=client.model_id,
                    final_url=harness.current_url(),
                    final_text=final_text,
                    turn_count=turn_count,
                    artifact_dir=str(harness.artifact_dir),
                )

            pending_safety_checks = computer_call.get("pending_safety_checks") or []
            if pending_safety_checks:
                raise RuntimeError(f"OpenAI computer tool returned pending safety checks: {json.dumps(pending_safety_checks)}")

            actions = list(computer_call.get("actions", []))
            if progress_callback is not None:
                progress_callback("turn_started", {"turn_index": turn_count + 1, "actions": actions})
            harness.execute_actions(actions)
            screenshot_path, screenshot_base64 = harness.capture_screenshot(f"turn-{turn_count + 1}")
            if progress_callback is not None:
                progress_callback(
                    "screenshot_captured",
                    {"turn_index": turn_count + 1, "screenshot_path": screenshot_path, "current_url": harness.current_url()},
                )
            response = client.continue_with_screenshot(response["id"], computer_call["call_id"], screenshot_base64)
            _write_json_artifact(harness.artifact_dir, f"response-turn-{turn_count + 1}", response)
            turn_count += 1

        raise RuntimeError(f"Agentic run exceeded the configured turn limit ({max_turns}).")
    finally:
        harness.close()


def extract_computer_call(response: dict[str, Any]) -> dict[str, Any] | None:
    for item in response.get("output", []):
        if item.get("type") == "computer_call":
            return item
    return None


def extract_reasoning_summary(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "reasoning":
            continue
        for summary_item in item.get("summary", []):
            text = summary_item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return " ".join(parts)


def extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _write_json_artifact(artifact_dir: Path, stem: str, payload: dict[str, Any]) -> str:
    path = artifact_dir / f"{stem}-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path)


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
    }
    return aliases.get(normalized.upper(), normalized)
