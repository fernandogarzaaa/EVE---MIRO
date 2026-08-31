"""Counterfactuals are model-generated, never fact."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eve_miro.core.world.events import ProvenanceKind


class Counterfactual(BaseModel):
    id: str
    base_experience_id: str
    intervention: str
    predicted_delta: dict[str, Any] = Field(default_factory=dict)
    label: str = "model-generated"
    fact: bool = False
    provenance_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    disclaimer: str = (
        "MODEL-GENERATED counterfactual, not fact. "
        "Do not treat this as an observation of the real world."
    )

    def assert_not_fact(self) -> None:
        if self.fact or self.label != "model-generated":
            raise ValueError("counterfactuals must be labeled model-generated, not fact")
