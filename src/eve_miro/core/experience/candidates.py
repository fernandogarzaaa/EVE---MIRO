"""Experience candidates emitted from agent-action trajectories."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eve_miro.core.world.events import ProvenanceKind


class Trajectory(BaseModel):
    simulation_id: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    predicted_series: dict[str, list[float]] = Field(default_factory=dict)


class ExperienceCandidate(BaseModel):
    id: str
    agent_id: str | None = None
    episode_id: str
    layer: str  # agent | population | simulator_vs_reality
    context: dict[str, Any] = Field(default_factory=dict)
    prediction: dict[str, Any] | None = None
    action: str | None = None
    observation: dict[str, Any] = Field(default_factory=dict)
    outcome: str | None = None
    temporal_window: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(
        default_factory=lambda: {"kind": ProvenanceKind.SIMULATED.value, "raw": False}
    )
