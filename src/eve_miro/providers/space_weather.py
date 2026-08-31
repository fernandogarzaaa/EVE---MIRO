"""NOAA SWPC GOES X-ray flux. Global series; location omitted. OBSERVED."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fixtures_enabled, http_get_json, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

XRAY_URL = "https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json"
FIXTURE = "noaa_swpc_xrays.json"


def _trim_points(points: list[dict], per_energy: int = 3) -> list[dict]:
    by: dict[str, list[dict]] = defaultdict(list)
    for p in points:
        by[str(p.get("energy") or "unknown")].append(p)
    out: list[dict] = []
    for key in sorted(by):
        out.extend(by[key][-per_energy:])
    return out


class SpaceWeatherProvider:
    name = "spaceweather"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="swpc.goes.xrays",
            fields={"time_tag": "datetime", "flux": "float", "energy": "str", "satellite": "int"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="spaceweather",
            dataset="swpc.goes.xrays-6-hour",
            license="NOAA SWPC public domain",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.swpc.noaa.gov/",
            notes="GOES X-ray flux. Global series; location omitted.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("SPACEWEATHER_LIVE"),
            message="NOAA SWPC GOES X-rays",
        )

    def normalize(self, payload: object, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="spaceweather", dataset="swpc.goes.xrays", version="goes-primary", license="US public domain")
        points = payload if isinstance(payload, list) else list(payload.get("data") or [])
        points = _trim_points(points)
        events: list[WorldEvent] = []
        for p in points:
            tag = p.get("time_tag")
            t = as_utc(tag) if tag else ingested_at
            energy = p.get("energy") or "unknown"
            events.append(
                WorldEvent(
                    id=f"swpc:xray:{energy}:{t.strftime('%Y%m%dT%H%M%S')}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=None,
                    event_type="spaceweather.xray",
                    payload={
                        "time_tag": tag,
                        "satellite": p.get("satellite"),
                        "flux": p.get("flux"),
                        "observed_flux": p.get("observed_flux"),
                        "energy": energy,
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.95),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="minute",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window, region or PHILIPPINES
        payload = None
        if live_requested("SPACEWEATHER_LIVE"):
            try:
                payload = await http_get_json(XRAY_URL, timeout=20.0)
            except Exception:
                payload = None
        if payload is None:
            payload = load_fixture(FIXTURE)
        return self.normalize(payload)
