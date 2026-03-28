from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .domain import PuzzleAdapter, PuzzleInstance, SandboxSession, ScoredAttempt


@dataclass
class WordleAdapter(PuzzleAdapter):
    puzzle_key: str = "wordle"
    display_name: str = "Wordle"

    def fetch_puzzle(self, target_date: date) -> PuzzleInstance:
        answer = ["cider", "crane", "baker"][target_date.day % 3]
        return PuzzleInstance(
            puzzle_key=self.puzzle_key,
            date=target_date,
            display_name=self.display_name,
            source_url="https://www.nytimes.com/games/wordle/index.html",
            snapshot_data={
                "visible_text": "Guess the five-letter word in six tries.",
                "interactables": ["#board", "#keyboard"],
                "answer": answer,
            },
        )

    def setup_session(self, session: SandboxSession, puzzle: PuzzleInstance) -> None:
        session.navigate(puzzle.source_url)

    def instructions(self, puzzle: PuzzleInstance) -> str:
        return "Solve Wordle by submitting a single five-letter answer."

    def is_terminal(self, session: SandboxSession, puzzle: PuzzleInstance) -> bool:
        return "submitted_answer" in session.snapshot().get("state", {})

    def score(self, session: SandboxSession, puzzle: PuzzleInstance, trace: list[dict[str, Any]]) -> ScoredAttempt:
        submitted = session.snapshot().get("state", {}).get("submitted_answer")
        correct = submitted == puzzle.snapshot_data["answer"]
        return ScoredAttempt(
            solve_status="solved" if correct else "failed",
            normalized_score=100.0 if correct else 0.0,
            raw_metrics={"submitted_answer": submitted, "expected_answer": puzzle.snapshot_data["answer"]},
            failure_category=None if correct else "incorrect_answer",
        )


@dataclass
class SudokuAdapter(PuzzleAdapter):
    puzzle_key: str = "sudoku"
    display_name: str = "Sudoku"

    def fetch_puzzle(self, target_date: date) -> PuzzleInstance:
        solution = "534678912672195348198342567"
        return PuzzleInstance(
            puzzle_key=self.puzzle_key,
            date=target_date,
            display_name=self.display_name,
            source_url="https://example.com/sudoku",
            snapshot_data={
                "visible_text": "Fill the Sudoku grid so every row, column, and box contains 1-9.",
                "interactables": ["#grid", "#submit"],
                "answer": solution,
                "grid": "53..7....6..195...",
            },
        )

    def setup_session(self, session: SandboxSession, puzzle: PuzzleInstance) -> None:
        session.navigate(puzzle.source_url)

    def instructions(self, puzzle: PuzzleInstance) -> str:
        return "Submit the solved Sudoku grid as a compact row-major string."

    def is_terminal(self, session: SandboxSession, puzzle: PuzzleInstance) -> bool:
        return "submitted_answer" in session.snapshot().get("state", {})

    def score(self, session: SandboxSession, puzzle: PuzzleInstance, trace: list[dict[str, Any]]) -> ScoredAttempt:
        submitted = session.snapshot().get("state", {}).get("submitted_answer")
        correct = submitted == puzzle.snapshot_data["answer"]
        return ScoredAttempt(
            solve_status="solved" if correct else "failed",
            normalized_score=100.0 if correct else 15.0 if submitted else 0.0,
            raw_metrics={"submitted_answer": submitted, "expected_answer": puzzle.snapshot_data["answer"]},
            failure_category=None if correct else "incorrect_answer",
        )


@dataclass
class ChessDotComDailyPuzzleAdapter(PuzzleAdapter):
    puzzle_key: str = "chess-puzzle"
    display_name: str = "Chess.com Puzzle of the Day"

    def fetch_puzzle(self, target_date: date) -> PuzzleInstance:
        answer = "Qg7#"
        return PuzzleInstance(
            puzzle_key=self.puzzle_key,
            date=target_date,
            display_name=self.display_name,
            source_url="https://www.chess.com/puzzles/problem",
            snapshot_data={
                "visible_text": "Find the best move for the side to move.",
                "interactables": ["#board", ".piece"],
                "answer": answer,
            },
        )

    def setup_session(self, session: SandboxSession, puzzle: PuzzleInstance) -> None:
        session.navigate(puzzle.source_url)

    def instructions(self, puzzle: PuzzleInstance) -> str:
        return "Submit the best move in SAN notation."

    def is_terminal(self, session: SandboxSession, puzzle: PuzzleInstance) -> bool:
        return "submitted_answer" in session.snapshot().get("state", {})

    def score(self, session: SandboxSession, puzzle: PuzzleInstance, trace: list[dict[str, Any]]) -> ScoredAttempt:
        submitted = session.snapshot().get("state", {}).get("submitted_answer")
        correct = submitted == puzzle.snapshot_data["answer"]
        return ScoredAttempt(
            solve_status="solved" if correct else "failed",
            normalized_score=100.0 if correct else 20.0 if submitted else 0.0,
            raw_metrics={"submitted_answer": submitted, "expected_answer": puzzle.snapshot_data["answer"]},
            failure_category=None if correct else "incorrect_answer",
        )


def default_puzzle_adapters() -> list[PuzzleAdapter]:
    return [WordleAdapter(), SudokuAdapter(), ChessDotComDailyPuzzleAdapter()]
