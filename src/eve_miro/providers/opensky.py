"""OpenSky Network ADS-B states. Aircraft are vehicles, not people. OBSERVED."""

from __future__ import annotations

from datetime import datetime, timezone

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
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json, live_requested
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

STATES_URL = "https://opensky-network.org/api/states/all"
FIXTURE = "opensky_ph.json"

# OpenSky state vector indices (REST API)
_ICAO24, _CALLSIGN, _ORIGIN = 0, 1, 2
_TIME_POS, _LAST_CONTACT = 3, 4
_LON, _LAT, _BARO = 5, 6, 7
_ON_GROUND, _VELOCITY, _TRACK = 8, 9, 10


class OpenSkyProvider:
    name = "opensky"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="opensky.states",
            fields={
                "icao24": "str",
                "callsign": "str",
                "lon": "float",
                "lat": "float",
                "baro_altitude": "float m",
                "velocity": "float m/s",
                "true_track": "float deg",
                "on_ground": "bool",
                "last_contact": "unix_s",
            },
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="opensky",
            dataset="states",
            license="OpenSky Network terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://opensky-network.org/",
            notes="ADS-B state vectors. Aircraft/vehicles only; no person tracking. Poll ~30s.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("OPENSKY_LIVE"),
            message="OpenSky ADS-B states (PH bbox)",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="opensky", dataset="states", version="1", license="OpenSky Network terms")
        events: list[WorldEvent] = []
        snap_t = payload.get("time")
        for vec in payload.get("states") or []:
            if not vec or len(vec) < 11:
                continue
            lat, lon = vec[_LAT], vec[_LON]
            if lat is None or lon is None:
                continue
            icao24 = str(vec[_ICAO24] or "").strip().lower()
            callsign = str(vec[_CALLSIGN] or "").strip()
            last_contact = vec[_LAST_CONTACT]
            t = (
                datetime.fromtimestamp(float(last_contact), tz=timezone.utc)
                if last_contact
                else (
                    datetime.fromtimestamp(float(snap_t), tz=timezone.utc)
                    if snap_t
                    else ingested_at
                )
            )
            events.append(
                WorldEvent(
                    id=f"opensky:{icao24}:{int(t.timestamp())}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=Location(lat=float(lat), lon=float(lon), altitude=float(vec[_BARO]) if vec[_BARO] is not None else None),
                    entity=Entity(id=icao24, type="aircraft"),
                    event_type="aircraft.position",
                    payload={
                        "icao24": icao24,
                        "callsign": callsign,
                        "lon": float(lon),
                        "lat": float(lat),
                        "baro_altitude": vec[_BARO],
                        "velocity": vec[_VELOCITY],
                        "true_track": vec[_TRACK],
                        "on_ground": bool(vec[_ON_GROUND]),
                        "last_contact": last_contact,
                        "origin_country": vec[_ORIGIN] if len(vec) > _ORIGIN else None,
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
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
        region = region or PHILIPPINES
        async def _live():
            return await http_get_json(
                STATES_URL,
                params={
                    "lamin": region.min_lat,
                    "lomin": region.min_lon,
                    "lamax": region.max_lat,
                    "lomax": region.max_lon,
                },
                timeout=25.0,
            )

        payload = await fetch_live_or_fixture("OPENSKY_LIVE", FIXTURE, _live)
        events = self.normalize(payload)
        return [e for e in events if e.location and region.contains(e.location.lat, e.location.lon)]
