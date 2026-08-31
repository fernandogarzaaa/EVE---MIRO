"""USGS FDSN GeoJSON earthquake adapter. OBSERVED. Filtered to the Philippines bbox."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Location,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FDSN = "https://earthquake.usgs.gov/fdsnws/event/1/query"


class USGSProvider:
    name = "usgs"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="usgs.fdsn.geojson",
            fields={"mag": "float", "place": "str", "depth_km": "float", "time": "epoch_ms"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="usgs",
            dataset="fdsn_event_geojson",
            license="Public domain (USGS)",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://earthquake.usgs.gov/",
            notes="FDSN GeoJSON. Filtered to PH bbox. No person-level data.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and os.environ.get("USGS_LIVE", "0") != "1",
            message="USGS FDSN GeoJSON",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="usgs", dataset="fdsn_event_geojson", version="1", license="USGS public domain")
        events: list[WorldEvent] = []
        for feat in payload.get("features") or []:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None, None]
            lon, lat = float(coords[0]), float(coords[1])
            depth = coords[2] if len(coords) > 2 else None
            t_ms = props.get("time")
            t = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc) if t_ms else ingested_at
            eid = str(feat.get("id") or props.get("code") or f"usgs:{t.isoformat()}")
            events.append(
                WorldEvent(
                    id=f"usgs:{eid}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=Location(lat=lat, lon=lon, altitude=float(depth) if depth is not None else None),
                    event_type="earthquake.event",
                    payload={
                        "mag": props.get("mag"),
                        "place": props.get("place"),
                        "magType": props.get("magType"),
                        "title": props.get("title"),
                        "status": props.get("status"),
                        "depth_km": depth,
                        "url": props.get("url"),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="event",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        region = region or PHILIPPINES
        async def _live():
            url = (
                f"{FDSN}?format=geojson"
                f"&minlatitude={region.min_lat}&maxlatitude={region.max_lat}"
                f"&minlongitude={region.min_lon}&maxlongitude={region.max_lon}"
                f"&starttime={as_utc(window.start).date()}&endtime={as_utc(window.end).date()}"
                f"&limit=200"
            )
            return await http_get_json(url)

        payload = await fetch_live_or_fixture("USGS_LIVE", "usgs_philippines.json", _live)
        events = self.normalize(payload)
        start, end = as_utc(window.start), as_utc(window.end)
        out = []
        for e in events:
            if not region.contains(e.location.lat, e.location.lon):  # type: ignore[union-attr]
                continue
            if start <= e.temporal.effective_time <= end:
                out.append(e)
        return out
