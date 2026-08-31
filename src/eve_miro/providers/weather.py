"""Open-Meteo weather adapter. Archive/previous-runs → OBSERVED; forecast endpoint → FORECAST."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import polars as pl

from eve_miro.config import MANILA_LAT, MANILA_LON, PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Location,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fixtures_enabled, http_get_json, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,relative_humidity_2m,weather_code"


class OpenMeteoProvider:
    name = "openmeteo"

    def __init__(self, *, mode: str = "archive") -> None:
        if mode not in {"archive", "forecast"}:
            raise ValueError("mode must be archive or forecast")
        self.mode = mode

    def schema(self) -> DataSchema:
        kind = ProvenanceKind.FORECAST if self.mode == "forecast" else ProvenanceKind.OBSERVED
        return DataSchema(
            name="openmeteo.hourly",
            fields={
                "temperature_2m": "float C",
                "precipitation": "float mm",
                "wind_speed_10m": "float km/h",
                "wind_gusts_10m": "float km/h",
                "relative_humidity_2m": "float %",
            },
            provenance_kind=kind,
        )

    def provenance(self) -> ProviderProvenance:
        kind = ProvenanceKind.FORECAST if self.mode == "forecast" else ProvenanceKind.OBSERVED
        return ProviderProvenance(
            provider="openmeteo",
            dataset="archive" if self.mode == "archive" else "forecast",
            license="CC BY 4.0 (Open-Meteo / underlying weather models)",
            kind=kind,
            homepage="https://open-meteo.com/",
            notes="No API key. Archive is OBSERVED (model analysis / historical). Forecast is FORECAST.",
        )

    async def health(self) -> ProviderHealth:
        interval = PROVIDER_INTERVALS[self.name].total_seconds()
        return ProviderHealth(
            name=self.name,
            available=True,
            message=f"mode={self.mode}",
            interval_seconds=interval,
            using_fixtures=fixtures_enabled() and os.environ.get("OPENMETEO_LIVE", "0") != "1",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        """Normalize Open-Meteo JSON via polars. Used by tests against fixtures."""
        ingested_at = ingested_at or utcnow()
        kind = ProvenanceKind.FORECAST if self.mode == "forecast" else ProvenanceKind.OBSERVED
        lat = float(payload.get("latitude") or MANILA_LAT)
        lon = float(payload.get("longitude") or MANILA_LON)
        hourly = payload["hourly"]
        df = pl.DataFrame(hourly)
        events: list[WorldEvent] = []
        source = Source(
            provider="openmeteo",
            dataset=self.mode,
            version=str(payload.get("generationtime_ms", "")),
            license="CC-BY-4.0",
        )
        for row in df.iter_rows(named=True):
            t = as_utc(row["time"])
            eid = f"openmeteo:{self.mode}:{lat:.4f}:{lon:.4f}:{t.strftime('%Y%m%dT%H%M')}"
            events.append(
                WorldEvent(
                    id=eid,
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=Location(lat=lat, lon=lon),
                    event_type="weather.hourly",
                    payload={
                        k: row.get(k)
                        for k in (
                            "temperature_2m",
                            "precipitation",
                            "wind_speed_10m",
                            "wind_gusts_10m",
                            "relative_humidity_2m",
                            "weather_code",
                        )
                    },
                    provenance=Provenance(kind=kind, raw=True, confidence=0.85 if kind == ProvenanceKind.FORECAST else 0.95),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=t + timedelta(hours=1),
                        resolution="hourly",
                    ),
                    information_cutoff=t if kind == ProvenanceKind.OBSERVED else ingested_at,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        region = region or PHILIPPINES
        live = os.environ.get("OPENMETEO_LIVE", "0") == "1" and not fixtures_enabled()
        payload = None
        if live:
            try:
                payload = await self._fetch_live(window)
            except Exception:
                payload = None
        if payload is None:
            name = (
                "openmeteo_manila_forecast.json"
                if self.mode == "forecast"
                else "openmeteo_manila_archive.json"
            )
            payload = load_fixture(name)
        events = self.normalize(payload)
        start = as_utc(window.start)
        end = as_utc(window.end)
        return [e for e in events if start <= e.temporal.effective_time <= end and (e.location is None or region.contains(e.location.lat, e.location.lon))]

    async def _fetch_live(self, window: TimeWindow) -> dict:
        start = as_utc(window.start).date().isoformat()
        end = as_utc(window.end).date().isoformat()
        if self.mode == "archive":
            url = (
                f"{ARCHIVE_URL}?latitude={MANILA_LAT}&longitude={MANILA_LON}"
                f"&start_date={start}&end_date={end}&hourly={HOURLY}&timezone=UTC"
            )
        else:
            url = (
                f"{FORECAST_URL}?latitude={MANILA_LAT}&longitude={MANILA_LON}"
                f"&hourly={HOURLY}&timezone=UTC&forecast_days=3"
            )
        return await http_get_json(url)
