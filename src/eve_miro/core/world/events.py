"""WorldEvent contract. Provenance kinds are mandatory and never mixed."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eve_miro.core.world.temporal import as_utc


class ProvenanceKind(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    FORECAST = "forecast"
    SIMULATED = "simulated"


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    dataset: str
    version: str | None = None
    license: str | None = None


class Location(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: float
    lon: float
    altitude: float | None = None


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: str


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ProvenanceKind
    raw: bool = True
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float | None = None
    conflicted: bool = False
    notes: str | None = None


class Temporal(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_time: datetime
    effective_time: datetime
    valid_from: datetime
    valid_until: datetime | None = None
    resolution: str = "event"

    @field_validator("source_time", "effective_time", "valid_from", "valid_until", mode="before")
    @classmethod
    def _utc(cls, v: object) -> object:
        if v is None:
            return v
        return as_utc(v)  # type: ignore[arg-type]


class WorldEvent(BaseModel):
    """Atomic observation or generated fact. Frozen: history is never mutated."""

    model_config = ConfigDict(frozen=True)

    id: str
    source: Source
    observed_at: datetime
    ingested_at: datetime
    location: Location | None = None
    entity: Entity | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance
    temporal: Temporal
    information_cutoff: datetime | None = None

    @field_validator("observed_at", "ingested_at", "information_cutoff", mode="before")
    @classmethod
    def _utc(cls, v: object) -> object:
        if v is None:
            return v
        return as_utc(v)  # type: ignore[arg-type]

    @property
    def kind(self) -> ProvenanceKind:
        return self.provenance.kind

    def effective_time(self) -> datetime:
        return self.temporal.effective_time
