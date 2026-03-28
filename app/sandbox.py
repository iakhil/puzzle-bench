from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import uuid

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

    def observe(self, instructions: str, remaining_steps: int) -> Observation:
        return Observation(
            current_url=self.current_url,
            title=self.title,
            visible_text=self.visible_text,
            interactables=self.interactables,
            screenshot_path=None,
            instructions=instructions,
            remaining_steps=remaining_steps,
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
    @property
    def provider_name(self) -> str:
        return "local-playwright"

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
