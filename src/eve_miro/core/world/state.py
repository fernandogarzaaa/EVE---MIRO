"""WorldState snapshot. Reconstructed from the event log; never mutated in place."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eve_miro.core.world.provenance import ProvenanceGraph
from eve_miro.core.world.temporal import as_utc


class Geography(BaseModel):
    model_config = ConfigDict(frozen=True)
    region: str = "philippines"
    bbox: tuple[float, float, float, float] = (4.2, 21.2, 116.5, 127.0)
    centroid: tuple[float, float] = (14.5995, 120.9842)


class Environment(BaseModel):
    """Weather and seismic summary at timestamp."""

    model_config = ConfigDict(frozen=True)
    weather: dict[str, Any] = Field(default_factory=dict)
    seismic: dict[str, Any] = Field(default_factory=dict)
    hazards: list[dict[str, Any]] = Field(default_factory=list)


class Economy(BaseModel):
    model_config = ConfigDict(frozen=True)
    indicators: dict[str, Any] = Field(default_factory=dict)


class Infrastructure(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: dict[str, Any] = Field(default_factory=dict)


class Mobility(BaseModel):
    model_config = ConfigDict(frozen=True)
    aircraft_count: int = 0
    vessel_count: int = 0
    traffic_index: float | None = None
    samples: list[dict[str, Any]] = Field(default_factory=list)


class InformationLayer(BaseModel):
    model_config = ConfigDict(frozen=True)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    news_mentions: int = 0


class Population(BaseModel):
    """Statistical personas only — never a named real person."""

    model_config = ConfigDict(frozen=True)
    synthetic_n: int = 0
    notes: str = "Synthetic statistical personas. Not real people. Public data only."
    demographics: dict[str, Any] = Field(default_factory=dict)


class WorldState(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: str
    timestamp: datetime
    information_cutoff: datetime
    geography: Geography = Field(default_factory=Geography)
    environment: Environment = Field(default_factory=Environment)
    economy: Economy = Field(default_factory=Economy)
    infrastructure: Infrastructure = Field(default_factory=Infrastructure)
    mobility: Mobility = Field(default_factory=Mobility)
    information: InformationLayer = Field(default_factory=InformationLayer)
    population: Population = Field(default_factory=Population)
    events: list[str] = Field(default_factory=list)
    provenance_graph: ProvenanceGraph = Field(default_factory=ProvenanceGraph)
    quality: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", "information_cutoff", mode="before")
    @classmethod
    def _utc(cls, v: object) -> object:
        return as_utc(v)  # type: ignore[arg-type]
