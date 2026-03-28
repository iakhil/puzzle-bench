from __future__ import annotations

from dataclasses import dataclass

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
