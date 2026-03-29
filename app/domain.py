from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class RunBudget:
    max_steps: int
    max_seconds: int


@dataclass(frozen=True)
class PuzzleInstance:
    puzzle_key: str
    date: date
    display_name: str
    source_url: str
    snapshot_data: dict[str, Any]


@dataclass(frozen=True)
class Observation:
    current_url: str
    title: str
    visible_text: str
    interactables: list[str]
    screenshot_path: str | None
    instructions: str
    remaining_steps: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentAction:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDecision:
    action: AgentAction
    rationale: str


@dataclass(frozen=True)
class StepResult:
    observation: Observation
    step_artifacts: dict[str, Any]


@dataclass(frozen=True)
class ScoredAttempt:
    solve_status: str
    normalized_score: float
    raw_metrics: dict[str, Any]
    failure_category: str | None = None


@dataclass(frozen=True)
class RunContext:
    run_id: str
    model_id: str
    provider: str
    budget: RunBudget
    puzzle_instance: PuzzleInstance
    started_at: datetime


class SandboxSession(ABC):
    @abstractmethod
    def navigate(self, url: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def click(self, selector: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def type_text(self, selector: str, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def press_key(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def scroll(self, amount: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, script: str) -> Any:
        raise NotImplementedError

    @abstractmethod
    def observe(self, instructions: str, remaining_steps: int) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class SandboxProvider(ABC):
    @abstractmethod
    def start_session(self, puzzle: PuzzleInstance, run_id: str) -> SandboxSession:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError


class PuzzleAdapter(ABC):
    puzzle_key: str
    display_name: str

    @abstractmethod
    def fetch_puzzle(self, target_date: date) -> PuzzleInstance:
        raise NotImplementedError

    @abstractmethod
    def setup_session(self, session: SandboxSession, puzzle: PuzzleInstance) -> None:
        raise NotImplementedError

    @abstractmethod
    def instructions(self, puzzle: PuzzleInstance) -> str:
        raise NotImplementedError

    @abstractmethod
    def observe(self, session: SandboxSession, puzzle: PuzzleInstance, remaining_steps: int) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def is_terminal(self, session: SandboxSession, puzzle: PuzzleInstance) -> bool:
        raise NotImplementedError

    @abstractmethod
    def score(self, session: SandboxSession, puzzle: PuzzleInstance, trace: list[dict[str, Any]]) -> ScoredAttempt:
        raise NotImplementedError


class ModelAdapter(ABC):
    provider: str
    model_id: str

    @abstractmethod
    def next_action(self, observation: Observation, run_state: dict[str, Any]) -> AgentDecision:
        raise NotImplementedError
