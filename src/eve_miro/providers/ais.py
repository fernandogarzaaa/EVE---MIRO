"""AIS vessel positions. Vehicles, not people. Live path requires AISSTREAM_API_KEY."""

from __future__ import annotations

import os
from datetime import datetime

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Entity,
    Location,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.errors import ProviderError
from eve_miro.providers.common import fixtures_enabled, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FIXTURE = "aisstream_ph.json"


class AISStreamProvider:
    name = "aisstream"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="aisstream.positions",
            fields={
                "mmsi": "int",
                "lat": "float",
                "lon": "float",
                "sog": "float kn",
                "cog": "float deg",
                "destination": "str",
            },
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="aisstream",
            dataset="ais.positions",
            license="AISStream terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://aisstream.io/",
            notes="Public AIS vessel positions (vehicles). Live WebSocket requires AISSTREAM_API_KEY.",
        )

    async def health(self) -> ProviderHealth:
        has_key = bool(os.environ.get("AISSTREAM_API_KEY"))
        using = fixtures_enabled() and not live_requested("AISSTREAM_LIVE")
        return ProviderHealth(
            name=self.name,
            available=True if using or has_key else fixtures_enabled(),
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=using,
            message="AIS fixture" if using else ("AISStream key present" if has_key else "no AISSTREAM_API_KEY"),
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="aisstream", dataset="ais.positions", version="1", license="AISStream terms")
        events: list[WorldEvent] = []
        for row in payload.get("vessels") or payload.get("messages") or []:
            lat, lon = row.get("lat"), row.get("lon")
            if lat is None or lon is None:
                continue
            ts = row.get("timestamp") or row.get("time")
            t = as_utc(ts) if ts else ingested_at
            mmsi = row.get("mmsi")
            events.append(
                WorldEvent(
                    id=f"ais:{mmsi}:{t.strftime('%Y%m%dT%H%M%S')}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=Location(lat=float(lat), lon=float(lon)),
                    entity=Entity(id=str(mmsi), type="vessel"),
                    event_type="vessel.position",
                    payload={
                        "mmsi": mmsi,
                        "lat": float(lat),
                        "lon": float(lon),
                        "sog": row.get("sog"),
                        "cog": row.get("cog"),
                        "destination": row.get("destination"),
                        "name": row.get("name"),
                        "ship_type": row.get("ship_type"),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.85),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="snapshot",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window
        region = region or PHILIPPINES
        if not live_requested("AISSTREAM_LIVE"):
            events = self.normalize(load_fixture(FIXTURE))
            return [e for e in events if e.location and region.contains(e.location.lat, e.location.lon)]
        if not (os.environ.get("AISSTREAM_API_KEY") or "").strip():
            raise ProviderError("AISSTREAM_API_KEY missing for live aisstream fetch")
        raise ProviderError(
            "AISStream live ingest is WebSocket-only; no REST snapshot exists. "
            "Fail closed rather than inventing vessel positions. Use FIXTURES=1."
        )
