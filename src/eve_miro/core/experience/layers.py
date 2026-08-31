"""Three explicit experience layers: agent, population, simulator-vs-reality."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from eve_miro.core.experience.candidates import ExperienceCandidate


class AgentExperience(BaseModel):
    layer: Literal["agent"] = "agent"
    agent_id: str | None = None
    candidate: ExperienceCandidate
    action: str | None = None
    observation: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class PopulationExperience(BaseModel):
    layer: Literal["population"] = "population"
    candidate: ExperienceCandidate
    observation: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class SimulatorExperience(BaseModel):
    """Prediction vs reality at the simulator layer (kinds stay unmixed)."""

    layer: Literal["simulator_vs_reality"] = "simulator_vs_reality"
    candidate: ExperienceCandidate
    predicted: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


WorldModelExperience = SimulatorExperience  # alias of simulator_vs_reality; old name still works

LayerModel = Union[AgentExperience, PopulationExperience, SimulatorExperience]
LAYER_NAMES = ("agent", "population", "simulator_vs_reality")


def as_layer(candidate: ExperienceCandidate) -> LayerModel:
    if candidate.layer == "agent":
        return AgentExperience(
            agent_id=candidate.agent_id,
            candidate=candidate,
            action=candidate.action,
            observation=dict(candidate.observation),
            outcome=candidate.outcome,
            context=dict(candidate.context),
        )
    if candidate.layer in {"simulator_vs_reality", "world_model"}:
        return SimulatorExperience(
            candidate=candidate,
            predicted=dict(candidate.prediction or {}),
            observed=dict(candidate.observation),
            outcome=candidate.outcome,
            context=dict(candidate.context),
        )
    if candidate.layer == "population":
        return PopulationExperience(
            candidate=candidate,
            observation=dict(candidate.observation),
            outcome=candidate.outcome,
            context=dict(candidate.context),
        )
    return SimulatorExperience(
        candidate=candidate,
        predicted=dict(candidate.prediction or {}),
        observed=dict(candidate.observation),
        outcome=candidate.outcome,
        context=dict(candidate.context),
    )


def layers_from_candidates(candidates: list[ExperienceCandidate]) -> list[LayerModel]:
    return [as_layer(c) for c in candidates]
