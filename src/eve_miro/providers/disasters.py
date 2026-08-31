"""GDACS multi-hazard alerts. OBSERVED. PH plus regional SEA events."""

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
from eve_miro.providers.common import fixtures_enabled, http_get_json, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
FIXTURE = "gdacs_events.json"
# Keep PH plus a wider SEA window so nearby typhoons/quakes are not dropped.
SEA = Region(name="southeast_asia", min_lat=-11.0, max_lat=28.5, min_lon=95.0, max_lon=141.0)


class GDACSProvider:
    name = "gdacs"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="gdacs.alerts",
            fields={
                "eventtype": "str",
                "alertlevel": "str",
                "name": "str",
                "fromdate": "datetime",
                "lat": "float",
                "lon": "float",
                "severity": "float",
            },
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="gdacs",
            dataset="alerts",
            license="GDACS terms (acknowledge source)",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.gdacs.org/",
            notes="Disaster alerts. PH bbox preferred; regional SEA events kept with location.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("GDACS_LIVE"),
            message="GDACS GeoJSON alerts",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="gdacs", dataset="alerts", version="1", license="GDACS")
        events: list[WorldEvent] = []
        for feat in payload.get("features") or []:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            if lat is None or lon is None:
                continue
            fromdate = props.get("fromdate")
            t = as_utc(fromdate) if fromdate else ingested_at
            sev = props.get("severitydata") or {}
            event_id = props.get("eventid")
            episode = props.get("episodeid")
            events.append(
                WorldEvent(
                    id=f"gdacs:{props.get('eventtype')}:{event_id}:{episode}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=Location(lat=float(lat), lon=float(lon)),
                    event_type="disaster.alert",
                    payload={
                        "eventtype": props.get("eventtype"),
                        "alertlevel": props.get("alertlevel"),
                        "name": props.get("name"),
                        "fromdate": fromdate,
                        "lat": float(lat),
                        "lon": float(lon),
                        "severity": sev.get("severity") if isinstance(sev, dict) else sev,
                        "severitytext": sev.get("severitytext") if isinstance(sev, dict) else None,
                        "country": props.get("country"),
                        "iso3": props.get("iso3"),
                        "glide": props.get("glide"),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=as_utc(props["todate"]) if props.get("todate") else None,
                        resolution="event",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = region or PHILIPPINES
        payload = None
        if live_requested("GDACS_LIVE"):
            try:
                start = as_utc(window.start).date().isoformat()
                end = as_utc(window.end).date().isoformat()
                payload = await http_get_json(
                    SEARCH_URL,
                    params={
                        "fromdate": start,
                        "todate": end,
                        "alertlevel": "Green;Orange;Red",
                    },
                    timeout=25.0,
                )
            except Exception:
                payload = None
        if payload is None:
            payload = load_fixture(FIXTURE)
        events = self.normalize(payload)
        start, end = as_utc(window.start), as_utc(window.end)
        out = []
        for e in events:
            if e.location and not SEA.contains(e.location.lat, e.location.lon):
                continue
            if start <= e.temporal.effective_time <= end:
                out.append(e)
        return out
