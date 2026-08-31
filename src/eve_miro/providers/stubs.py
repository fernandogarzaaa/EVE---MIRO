"""Honest stub providers: interface + fixture, health=unavailable unless FIXTURES=1."""

from __future__ import annotations

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.temporal import utcnow
from eve_miro.providers.common import fixtures_enabled
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow


class StubProvider:
    """Base stub. Does not invent live observations."""

    name = "stub"
    dataset = "fixture"
    license = "n/a"
    homepage: str | None = None
    kind = ProvenanceKind.OBSERVED
    notes = "Stub: no live adapter in v1. Set FIXTURES=1 to mark available and return []."

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
        if not fixtures_enabled():
            return []
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


class OpenSkyProvider(StubProvider):
    name = "opensky"
    dataset = "states"
    license = "OpenSky Network terms"
    homepage = "https://opensky-network.org/"
    notes = "Stub. Would map ADS-B states to aircraft.position OBSERVED. Poll ~30s. No person tracking."


class AISStreamProvider(StubProvider):
    name = "aisstream"
    dataset = "ais"
    license = "AISStream terms"
    homepage = "https://aisstream.io/"
    notes = "Stub. Would map vessel positions. Poll ~30s. Public AIS only; no person profiling."


class GDACSProvider(StubProvider):
    name = "gdacs"
    dataset = "alerts"
    license = "GDACS"
    homepage = "https://www.gdacs.org/"
    notes = "Stub. Disaster alerts. Poll ~10 min."


class GDELTProvider(StubProvider):
    name = "gdelt"
    dataset = "events"
    license = "GDELT"
    homepage = "https://www.gdeltproject.org/"
    notes = "Stub. News event counts, not article republication. Poll ~15 min."


class OSMProvider(StubProvider):
    name = "osm"
    dataset = "geospatial"
    license = "ODbL"
    homepage = "https://www.openstreetmap.org/"
    notes = "Stub. Roads/buildings extracts. Daily cadence."


class NASAProvider(StubProvider):
    name = "nasa"
    dataset = "eo"
    license = "NASA open data"
    homepage = "https://earthdata.nasa.gov/"
    notes = "Stub. Earth observation scenes. Hours-scale cadence."


class CelestrakProvider(StubProvider):
    name = "celestrak"
    dataset = "gp"
    license = "CelesTrak"
    homepage = "https://celestrak.org/"
    notes = "Stub. Space-object GP elements. ~6h cadence."


class CoinGeckoProvider(StubProvider):
    name = "coingecko"
    dataset = "markets"
    license = "CoinGecko API terms"
    homepage = "https://www.coingecko.com/"
    notes = "Stub. Public market indices only. ~5 min cadence."


class WorldBankProvider(StubProvider):
    name = "worldbank"
    dataset = "indicators"
    license = "CC BY 4.0"
    homepage = "https://data.worldbank.org/"
    notes = "Stub. Country-level demographics. Monthly/annual cadence. No person-level data."
