from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .domain import Observation, PuzzleAdapter, PuzzleInstance, SandboxSession, ScoredAttempt


@dataclass
class FixtureWordleAdapter(PuzzleAdapter):
    puzzle_key: str = "wordle"
    display_name: str = "Wordle Fixture"

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

    def observe(self, session: SandboxSession, puzzle: PuzzleInstance, remaining_steps: int) -> Observation:
        return session.observe(self.instructions(puzzle), remaining_steps)

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
class LiveWordleAdapter(PuzzleAdapter):
    puzzle_key: str = "wordle"
    display_name: str = "NYT Wordle"

    def fetch_puzzle(self, target_date: date) -> PuzzleInstance:
        return PuzzleInstance(
            puzzle_key=self.puzzle_key,
            date=target_date,
            display_name=self.display_name,
            source_url="https://www.nytimes.com/games/wordle/index.html",
            snapshot_data={
                "visible_text": "Guess the Wordle in 6 tries.",
                "interactables": ["[data-testid='Play']", "button[aria-label='Close']"],
                "source": "live-nyt",
            },
        )

    def setup_session(self, session: SandboxSession, puzzle: PuzzleInstance) -> None:
        session.navigate(puzzle.source_url)
        session.click("[data-testid='Play']")
        try:
            session.click("button[aria-label='Close']")
        except Exception:
            pass

    def instructions(self, puzzle: PuzzleInstance) -> str:
        return (
            "Play the live NYT Wordle in the browser. "
            "Use the `submit_guess` action with a valid five-letter word. "
            "You have six guesses. Base each next guess on the tile feedback in the observation metadata."
        )

    def observe(self, session: SandboxSession, puzzle: PuzzleInstance, remaining_steps: int) -> Observation:
        base = session.observe(self.instructions(puzzle), remaining_steps)
        wordle_state = _extract_wordle_state(session)
        board_summary = _summarize_wordle_rows(wordle_state["rows"])
        return Observation(
            current_url=base.current_url,
            title=base.title,
            visible_text=board_summary,
            interactables=base.interactables,
            screenshot_path=base.screenshot_path,
            instructions=base.instructions,
            remaining_steps=base.remaining_steps,
            metadata={"wordle": wordle_state},
        )

    def is_terminal(self, session: SandboxSession, puzzle: PuzzleInstance) -> bool:
        wordle_state = _extract_wordle_state(session)
        return bool(wordle_state["is_solved"] or wordle_state["is_failed"])

    def score(self, session: SandboxSession, puzzle: PuzzleInstance, trace: list[dict[str, Any]]) -> ScoredAttempt:
        wordle_state = _extract_wordle_state(session)
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
            raw_metrics={
                "submitted_rows": guesses_used,
                "rows": wordle_state["rows"],
            },
            failure_category=failure_category,
        )


def default_puzzle_adapters() -> list[PuzzleAdapter]:
    return [LiveWordleAdapter()]


def demo_puzzle_adapters() -> list[PuzzleAdapter]:
    return [FixtureWordleAdapter()]


def _extract_wordle_state(session: SandboxSession) -> dict[str, Any]:
    return session.evaluate(
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
