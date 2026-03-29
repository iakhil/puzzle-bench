from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import AgentAction, AgentDecision, ModelAdapter, Observation


@dataclass
class ScriptedModelAdapter(ModelAdapter):
    provider: str
    model_id: str

    def next_action(self, observation: Observation, run_state: dict[str, object]) -> AgentDecision:
        scripted_answer = run_state.get("scripted_answer")
        if scripted_answer and not run_state.get("submitted"):
            run_state["submitted"] = True
            return AgentDecision(
                action=AgentAction(kind="submit_answer", payload={"answer": scripted_answer}),
                rationale="Submitting the scripted answer for deterministic benchmark seeding.",
            )
        return AgentDecision(
            action=AgentAction(kind="finish", payload={}),
            rationale="No further deterministic action is available.",
        )


@dataclass
class ScriptedWordleModelAdapter(ModelAdapter):
    provider: str
    model_id: str
    guess_sequence: Sequence[str]

    def next_action(self, observation: Observation, run_state: dict[str, object]) -> AgentDecision:
        wordle_state = observation.metadata.get("wordle", {})
        submitted_rows = int(wordle_state.get("submitted_rows", 0))
        if wordle_state.get("is_solved") or wordle_state.get("is_failed"):
            return AgentDecision(
                action=AgentAction(kind="finish", payload={}),
                rationale="The game is already complete.",
            )
        if submitted_rows >= len(self.guess_sequence):
            return AgentDecision(
                action=AgentAction(kind="finish", payload={}),
                rationale="No scripted guesses remain.",
            )
        guess = self.guess_sequence[submitted_rows].lower()
        return AgentDecision(
            action=AgentAction(kind="submit_guess", payload={"guess": guess}),
            rationale=f"Submitting scripted Wordle guess {guess}.",
        )


@dataclass
class OpenAIWordleModelAdapter(ModelAdapter):
    provider: str = "openai"
    model_id: str = "gpt-5.4"
    api_base: str = "https://api.openai.com/v1/responses"

    def next_action(self, observation: Observation, run_state: dict[str, object]) -> AgentDecision:
        wordle_state = observation.metadata.get("wordle", {})
        if wordle_state.get("is_solved") or wordle_state.get("is_failed"):
            return AgentDecision(
                action=AgentAction(kind="finish", payload={}),
                rationale="The game is already complete.",
            )

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        payload = {
            "model": self.model_id,
            "instructions": (
                "You are solving a live Wordle puzzle. "
                "Return exactly one valid five-letter lowercase English word guess. "
                "Use the prior row feedback carefully. "
                "Do not explain your reasoning."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_prompt(observation, wordle_state),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "wordle_guess",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "guess": {
                                "type": "string",
                                "pattern": "^[a-z]{5}$",
                            }
                        },
                        "required": ["guess"],
                        "additionalProperties": False,
                    },
                }
            },
        }

        request = Request(
            self.api_base,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:  # pragma: no cover - networked path
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API request failed with status {exc.code}: {detail}") from exc
        except URLError as exc:  # pragma: no cover - networked path
            raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc

        guess = self._extract_guess(body)
        return AgentDecision(
            action=AgentAction(kind="submit_guess", payload={"guess": guess}),
            rationale=f"Submitting model-selected Wordle guess {guess}.",
        )

    def _build_prompt(self, observation: Observation, wordle_state: dict[str, object]) -> str:
        rows = wordle_state.get("rows", [])
        rendered_rows: list[str] = []
        for row in rows:
            guess = row.get("guess") or "empty"
            if row.get("submitted"):
                feedback = ", ".join(tile.get("state", "unknown") for tile in row.get("tiles", []))
                rendered_rows.append(f"Row {row.get('row')}: {guess} -> {feedback}")
            else:
                rendered_rows.append(f"Row {row.get('row')}: empty")
        return (
            f"Wordle observation:\n{chr(10).join(rendered_rows)}\n\n"
            f"Visible summary:\n{observation.visible_text}\n\n"
            "Return the next best five-letter guess."
        )

    def _extract_guess(self, response_body: dict[str, object]) -> str:
        text_value = ""
        if isinstance(response_body.get("output_text"), str):
            text_value = response_body["output_text"]
        if not text_value:
            for item in response_body.get("output", []):
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                        text_value = content["text"]
                        break
                if text_value:
                    break
        if not text_value:
            raise RuntimeError("OpenAI response did not contain text output.")
        try:
            parsed = json.loads(text_value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI response was not valid JSON: {text_value}") from exc
        guess = str(parsed.get("guess", "")).strip().lower()
        if len(guess) != 5 or not guess.isalpha():
            raise RuntimeError(f"OpenAI returned an invalid Wordle guess: {guess}")
        return guess
