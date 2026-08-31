"""Provider protocol. Adapters implement this; engines never talk to HTTP directly."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from eve_miro.config import Region, TimeWindow as CfgWindow
from eve_miro.core.world.events import ProvenanceKind, WorldEvent

TimeWindow = CfgWindow


class ProviderHealth(BaseModel):
    name: str
    available: bool
    last_success: datetime | None = None
    message: str = ""
    interval_seconds: float = 3600
    using_fixtures: bool = False


class DataSchema(BaseModel):
    name: str
    fields: dict[str, str] = Field(default_factory=dict)
    provenance_kind: ProvenanceKind = ProvenanceKind.OBSERVED


class ProviderProvenance(BaseModel):
    provider: str
    dataset: str
    license: str
    kind: ProvenanceKind
    homepage: str | None = None
    notes: str = ""


@runtime_checkable
class DataProvider(Protocol):
    name: str

    async def health(self) -> ProviderHealth: ...

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]: ...

    def schema(self) -> DataSchema: ...

    def provenance(self) -> ProviderProvenance: ...
