"""Honest stub base. Live adapters live in dedicated modules; nothing here needs a paid key.

AISStream still requires AISSTREAM_API_KEY for live WebSocket ingest (see ais.py).
That adapter ships a public vessel-position fixture and is registered as a real provider.
"""

from __future__ import annotations

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.providers.common import fixtures_enabled
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow


class StubProvider:
    """Base stub. Does not invent live observations."""

    name = "stub"
    dataset = "fixture"
    license = "n/a"
    homepage: str | None = None
    kind = ProvenanceKind.OBSERVED
    notes = "Stub: no live adapter. Set FIXTURES=1 to mark available and return []."

    async def health(self) -> ProviderHealth:
        available = fixtures_enabled()
        interval = PROVIDER_INTERVALS.get(self.name, PROVIDER_INTERVALS["osm"]).total_seconds()
        return ProviderHealth(
            name=self.name,
            available=available,
            using_fixtures=available,
            interval_seconds=interval,
            message="unavailable unless FIXTURES=1" if not available else "fixture mode (no live feed)",
        )

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window, region or PHILIPPINES
        return []

    def schema(self) -> DataSchema:
        return DataSchema(name=f"{self.name}.stub", provenance_kind=self.kind)

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider=self.name,
            dataset=self.dataset,
            license=self.license,
            kind=self.kind,
            homepage=self.homepage,
            notes=self.notes,
        )
