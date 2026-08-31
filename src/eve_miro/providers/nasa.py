"""Earth Search STAC (Element84) Sentinel-2 scenes. No NASA API key. OBSERVED catalog items."""

from __future__ import annotations

from datetime import datetime

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
from eve_miro.providers.common import fixtures_enabled, http_post_json, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

STAC_URL = "https://earth-search.aws.element84.com/v1/search"
FIXTURE = "nasa_stac_ph.json"
# Small Metro Manila bbox for live search (full PH bbox is huge).
MM_BBOX = [120.9, 14.4, 121.2, 14.8]


def _centroid(feat: dict) -> tuple[float, float] | None:
    bbox = feat.get("bbox") or []
    if len(bbox) >= 4:
        lon = (float(bbox[0]) + float(bbox[2])) / 2.0
        lat = (float(bbox[1]) + float(bbox[3])) / 2.0
        return lat, lon
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and coords and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    return None


class NASAProvider:
    name = "nasa"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="stac.sentinel2",
            fields={"id": "str", "datetime": "datetime", "collection": "str", "cloud_cover": "float"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="nasa",
            dataset="earth-search.sentinel-2-l2a",
            license="Sentinel / Earth Search open data",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://earth-search.aws.element84.com/",
            notes="STAC catalog adapter (no NASA key). Scene metadata only; assets listed by key.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("NASA_LIVE"),
            message="Earth Search STAC sentinel-2-l2a",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(
            provider="nasa",
            dataset="earth-search.sentinel-2-l2a",
            version="stac-1",
            license="open",
        )
        events: list[WorldEvent] = []
        for feat in payload.get("features") or []:
            props = feat.get("properties") or {}
            dt = props.get("datetime")
            t = as_utc(dt) if dt else ingested_at
            scene_id = feat.get("id") or f"stac:{t.isoformat()}"
            center = _centroid(feat)
            loc = Location(lat=center[0], lon=center[1]) if center else None
            events.append(
                WorldEvent(
                    id=f"stac:{scene_id}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=loc,
                    event_type="eo.scene",
                    payload={
                        "id": scene_id,
                        "datetime": dt,
                        "collection": feat.get("collection") or props.get("collection"),
                        "cloud_cover": props.get("eo:cloud_cover"),
                        "assets": list((feat.get("assets") or {}).keys()),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="scene",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        region = region or PHILIPPINES
        payload = None
        if live_requested("NASA_LIVE"):
            try:
                start = as_utc(window.start).strftime("%Y-%m-%dT%H:%M:%SZ")
                end = as_utc(window.end).strftime("%Y-%m-%dT%H:%M:%SZ")
                payload = await http_post_json(
                    STAC_URL,
                    {
                        "collections": ["sentinel-2-l2a"],
                        "bbox": MM_BBOX,
                        "datetime": f"{start}/{end}",
                        "limit": 3,
                    },
                    timeout=30.0,
                )
            except Exception:
                payload = None
        if payload is None:
            payload = load_fixture(FIXTURE)
        events = self.normalize(payload)
        start, end = as_utc(window.start), as_utc(window.end)
        out = []
        for e in events:
            if e.location and not region.contains(e.location.lat, e.location.lon):
                continue
            if start <= e.temporal.effective_time <= end:
                out.append(e)
        return out
