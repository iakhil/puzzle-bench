from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import uuid

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from .config import get_settings
from .domain import Observation, PuzzleInstance, SandboxProvider, SandboxSession


@dataclass
class LocalFixtureSandboxSession(SandboxSession):
    puzzle: PuzzleInstance
    run_id: str
    current_url: str
    title: str
    visible_text: str
    interactables: list[str]
    state: dict[str, object]

    def navigate(self, url: str) -> None:
        self.current_url = url

    def click(self, selector: str) -> None:
        self.state["last_click"] = selector

    def type_text(self, selector: str, text: str) -> None:
        typed = dict(self.state.get("typed", {}))
        typed[selector] = text
        self.state["typed"] = typed

    def press_key(self, key: str) -> None:
        pressed = list(self.state.get("pressed", []))
        pressed.append(key)
        self.state["pressed"] = pressed

    def scroll(self, amount: int) -> None:
        self.state["scroll"] = amount

    def evaluate(self, script: str):
        if script == "fixture_state":
            return self.state
        raise NotImplementedError("Fixture session does not support arbitrary script evaluation.")

    def observe(self, instructions: str, remaining_steps: int) -> Observation:
        return Observation(
            current_url=self.current_url,
            title=self.title,
            visible_text=self.visible_text,
            interactables=self.interactables,
            screenshot_path=None,
            instructions=instructions,
            remaining_steps=remaining_steps,
            metadata={},
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "current_url": self.current_url,
            "title": self.title,
            "visible_text": self.visible_text,
            "interactables": self.interactables,
            "state": self.state,
        }

    def close(self) -> None:
        return None


class LocalPlaywrightSandboxProvider(SandboxProvider):
    def __init__(self, headless: bool | None = None) -> None:
        self.headless = headless if headless is not None else os.getenv("GAME_BENCH_HEADLESS", "1") != "0"

    @property
    def provider_name(self) -> str:
        return "local-playwright"

    def start_session(self, puzzle: PuzzleInstance, run_id: str) -> SandboxSession:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=self.headless)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        return PlaywrightSandboxSession(
            puzzle=puzzle,
            run_id=run_id,
            playwright=playwright,
            browser=browser,
            page=page,
            state={},
        )


class LocalFixtureSandboxProvider(SandboxProvider):
    @property
    def provider_name(self) -> str:
        return "local-fixture"

    def start_session(self, puzzle: PuzzleInstance, run_id: str) -> SandboxSession:
        snapshot = puzzle.snapshot_data
        return LocalFixtureSandboxSession(
            puzzle=puzzle,
            run_id=run_id,
            current_url=puzzle.source_url,
            title=f"{puzzle.display_name} Fixture",
            visible_text=str(snapshot.get("visible_text", "")),
            interactables=list(snapshot.get("interactables", [])),
            state={"answer": snapshot.get("answer"), "grid": snapshot.get("grid")},
        )


@dataclass
class PlaywrightSandboxSession(SandboxSession):
    puzzle: PuzzleInstance
    run_id: str
    playwright: Playwright
    browser: Browser
    page: Page
    state: dict[str, object]

    def navigate(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(1500)

    def click(self, selector: str) -> None:
        self.page.locator(selector).click(timeout=15000)

    def type_text(self, selector: str, text: str) -> None:
        self.page.locator(selector).fill(text, timeout=15000)

    def press_key(self, key: str) -> None:
        self.page.keyboard.press(key)

    def scroll(self, amount: int) -> None:
        self.page.evaluate(f"window.scrollBy(0, {amount})")

    def evaluate(self, script: str):
        return self.page.evaluate(script)

    def observe(self, instructions: str, remaining_steps: int) -> Observation:
        screenshot_path = write_screenshot_artifact(self.run_id, self.page, "observation")
        visible_text = self.page.locator("body").inner_text(timeout=15000)[:4000]
        interactables = [
            item
            for item in self.page.evaluate(
                """
                () => Array.from(document.querySelectorAll('button'))
                  .map((button) => button.getAttribute('aria-label') || button.textContent || '')
                  .map((text) => text.trim())
                  .filter(Boolean)
                  .slice(0, 40)
                """
            )
        ]
        return Observation(
            current_url=self.page.url,
            title=self.page.title(),
            visible_text=visible_text,
            interactables=interactables,
            screenshot_path=screenshot_path,
            instructions=instructions,
            remaining_steps=remaining_steps,
            metadata={},
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "current_url": self.page.url,
            "title": self.page.title(),
            "visible_text": self.page.locator("body").inner_text(timeout=15000)[:4000],
            "state": self.state,
        }

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()


class BrowserbaseSandboxProvider(SandboxProvider):
    def __init__(self) -> None:
        self.api_key = os.getenv("BROWSERBASE_API_KEY")
        self.project_id = os.getenv("BROWSERBASE_PROJECT_ID")

    @property
    def provider_name(self) -> str:
        return "browserbase"

    def start_session(self, puzzle: PuzzleInstance, run_id: str) -> SandboxSession:
        if not self.api_key or not self.project_id:
            raise RuntimeError("Browserbase credentials are not configured.")
        raise NotImplementedError(
            "Browserbase session startup is scaffolded but requires the Browserbase SDK or REST integration."
        )


def write_run_artifact(run_id: str, artifact_type: str, payload: dict[str, object]) -> str:
    settings = get_settings()
    artifact_dir = settings.base_dir / "data" / "artifacts" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{artifact_type}-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return str(path)


def write_screenshot_artifact(run_id: str, page: Page, artifact_type: str) -> str:
    settings = get_settings()
    artifact_dir = settings.base_dir / "data" / "artifacts" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{artifact_type}-{uuid.uuid4().hex[:8]}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)
