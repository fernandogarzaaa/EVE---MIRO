"""Validated experience scores produced by the (stub) EVE engine."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.counterfactual import Counterfactual


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


class TransferResult(BaseModel):
    experience_id: str
    context: dict[str, Any]
    transferable: bool
    score: float
    notes: str = ""
