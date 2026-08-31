"""Validated experience scores produced by the (stub) EVE engine."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.counterfactual import Counterfactual
from eve_miro.core.world.provenance import ProvenanceGraph, ProvenanceNode


class ValidatedExperience(BaseModel):
    id: str
    candidate: ExperienceCandidate
    validity: float
    confidence: float
    prediction_error: float | None = None
    learning_value: float
    transferability: float
    retention_score: float
    counterfactuals: list[Counterfactual] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    artifact: dict[str, Any] | None = None
    layer: str = "agent"
    episode_id: str | None = None
    world_state_timestamp: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    source_providers: list[str] = Field(default_factory=list)
    provenance_graph: ProvenanceGraph | None = None

    def trace(self) -> list[ProvenanceNode]:
        """Why this validated experience: episode, world state, events, sources."""
        if self.provenance_graph is None:
            return []
        return self.provenance_graph.trace(self.id)

    def why(self) -> list[ProvenanceNode]:
        return self.trace()


class TransferResult(BaseModel):
    experience_id: str
    context: dict[str, Any]
    transferable: bool
    score: float
    notes: str = ""
