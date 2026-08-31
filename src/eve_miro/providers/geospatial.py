"""OpenStreetMap POIs (hospitals/airports). Overpass live is optional; fixtures are primary."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

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
from eve_miro.core.world.temporal import utcnow
from eve_miro.providers.common import fixtures_enabled, http_get_json, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QL = (
    '[out:json][timeout:15];('
    'node["amenity"="hospital"](14.4,120.9,14.8,121.2);'
    'node["aeroway"="aerodrome"](14.4,120.9,14.8,121.2);'
    ');out 10;'
)
FIXTURE = "osm_metro_manila_poi.json"


def _features(payload: dict) -> list[dict]:
    if payload.get("features"):
        return list(payload["features"])
    feats: list[dict] = []
    for el in payload.get("elements") or []:
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        feats.append(
            {
                "id": el.get("id"),
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": el.get("tags") or {},
            }
        )
    return feats


class OSMProvider:
    name = "osm"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="osm.poi",
            fields={"name": "str", "amenity": "str", "aeroway": "str", "lat": "float", "lon": "float"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="osm",
            dataset="poi.metro_manila",
            license="ODbL",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.openstreetmap.org/",
            notes="Hospitals/airports as map features (venues), not people. Overpass live is optional.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("OSM_LIVE"),
            message="OSM Metro Manila POIs",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="osm", dataset="poi.metro_manila", version="1", license="ODbL")
        events: list[WorldEvent] = []
        for feat in _features(payload):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            if lat is None or lon is None:
                continue
            fid = feat.get("id") or f"{lat:.4f}:{lon:.4f}"
            name = props.get("name") or "unnamed"
            kind = props.get("amenity") or props.get("aeroway") or "poi"
            events.append(
                WorldEvent(
                    id=f"osm:{fid}",
                    source=source,
                    observed_at=ingested_at,
                    ingested_at=ingested_at,
                    location=Location(lat=float(lat), lon=float(lon)),
                    entity=Entity(id=str(fid), type="poi"),
                    event_type="geo.poi",
                    payload={
                        "name": name,
                        "amenity": props.get("amenity"),
                        "aeroway": props.get("aeroway"),
                        "iata": props.get("iata"),
                        "icao": props.get("icao"),
                        "kind": kind,
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.85),
                    temporal=Temporal(
                        source_time=ingested_at,
                        effective_time=ingested_at,
                        valid_from=ingested_at,
                        valid_until=None,
                        resolution="map",
                    ),
                    information_cutoff=ingested_at,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window
        region = region or PHILIPPINES
        payload = None
        if live_requested("OSM_LIVE"):
            try:
                payload = await http_get_json(
                    f"{OVERPASS_URL}?data={quote(OVERPASS_QL)}",
                    timeout=20.0,
                )
            except Exception:
                payload = None
        if payload is None:
            payload = load_fixture(FIXTURE)
        events = self.normalize(payload)
        return [e for e in events if e.location and region.contains(e.location.lat, e.location.lon)]
