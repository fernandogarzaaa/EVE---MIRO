from __future__ import annotations

from datetime import datetime, timezone

from eve_miro.core.world.events import (
    Location,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)


def utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def make_event(
    eid: str,
    t: str,
    *,
    kind: ProvenanceKind = ProvenanceKind.OBSERVED,
    event_type: str = "weather.hourly",
    payload: dict | None = None,
    lat: float = 14.6,
    lon: float = 121.0,
    provider: str = "test",
) -> WorldEvent:
    dt = utc(t)
    return WorldEvent(
        id=eid,
        source=Source(provider=provider, dataset="fixture", license="test"),
        observed_at=dt,
        ingested_at=dt,
        location=Location(lat=lat, lon=lon),
        event_type=event_type,
        payload=payload or {"wind_speed_10m": 10.0},
        provenance=Provenance(kind=kind, raw=True, confidence=0.9),
        temporal=Temporal(
            source_time=dt,
            effective_time=dt,
            valid_from=dt,
            valid_until=None,
            resolution="hourly",
        ),
        information_cutoff=dt if kind == ProvenanceKind.OBSERVED else dt,
    )
