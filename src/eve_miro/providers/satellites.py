"""CelesTrak GP / TLE elements (stations group). OBSERVED elements, not a computed ground track."""

from __future__ import annotations

from datetime import datetime

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Entity,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json, live_requested
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
FIXTURE = "celestrak_stations.json"
_GP_FIELDS = (
    "OBJECT_NAME",
    "OBJECT_ID",
    "NORAD_CAT_ID",
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
    "CLASSIFICATION_TYPE",
    "EPHEMERIS_TYPE",
)


class CelestrakProvider:
    name = "celestrak"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="celestrak.gp",
            fields={"OBJECT_NAME": "str", "NORAD_CAT_ID": "int", "EPOCH": "datetime"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="celestrak",
            dataset="gp.stations",
            license="CelesTrak terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://celestrak.org/",
            notes="GP/TLE elements are OBSERVED. No SGP4 ground track (that would be DERIVED).",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("CELESTRAK_LIVE"),
            message="CelesTrak GP stations",
        )

    def normalize(self, payload: object, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="celestrak", dataset="gp.stations", version="gp", license="CelesTrak")
        rows = payload if isinstance(payload, list) else (payload.get("records") or payload.get("data") or [])
        events: list[WorldEvent] = []
        for row in rows:
            epoch = row.get("EPOCH")
            t = as_utc(epoch) if epoch else ingested_at
            norad = row.get("NORAD_CAT_ID")
            name = row.get("OBJECT_NAME") or "unknown"
            events.append(
                WorldEvent(
                    id=f"celestrak:{norad or name}:{t.strftime('%Y%m%dT%H%M%S')}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=None,
                    entity=Entity(id=str(norad if norad is not None else name), type="satellite"),
                    event_type="satellite.tle",
                    payload={k: row.get(k) for k in _GP_FIELDS},
                    provenance=Provenance(
                        kind=ProvenanceKind.OBSERVED,
                        raw=True,
                        confidence=0.95,
                        notes="TLE/GP elements; not a live ground-track position",
                    ),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="element_set",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window, region or PHILIPPINES
        async def _live():
            return await http_get_json(GP_URL, params={"GROUP": "stations", "FORMAT": "json"}, timeout=25.0)

        payload = await fetch_live_or_fixture("CELESTRAK_LIVE", FIXTURE, _live)
        return self.normalize(payload)
