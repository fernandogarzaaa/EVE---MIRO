"""World Bank country indicators for the Philippines. Annual, no person-level data."""

from __future__ import annotations

from datetime import datetime, timezone

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
from eve_miro.providers.common import fixtures_enabled, http_get_json, live_requested, load_fixture
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

WB_URL = "https://api.worldbank.org/v2/country/PH/indicator/{indicator}"
INDICATORS = ("SP.POP.TOTL", "NY.GDP.MKTP.CD")
FIXTURE = "worldbank_ph_indicators.json"


def _rows_from_payload(payload: object) -> list[dict]:
    if isinstance(payload, dict) and payload.get("responses"):
        rows: list[dict] = []
        for block in payload["responses"]:
            rows.extend(_rows_from_payload(block))
        return rows
    if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], list):
        return [r for r in payload[1] if isinstance(r, dict)]
    if isinstance(payload, dict) and payload.get("indicators"):
        return list(payload["indicators"])
    return []


class WorldBankProvider:
    name = "worldbank"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="worldbank.indicators",
            fields={"indicator": "str", "date": "year", "value": "float"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="worldbank",
            dataset="indicators.PH",
            license="CC BY 4.0",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://data.worldbank.org/",
            notes="Country-level PH indicators (population, GDP). Location is PH centroid. No person-level data.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("WORLDBANK_LIVE"),
            message="World Bank PH indicators",
        )

    def normalize(self, payload: object, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="worldbank", dataset="indicators.PH", version="v2", license="CC BY 4.0")
        loc = Location(lat=MANILA_LAT, lon=MANILA_LON)
        events: list[WorldEvent] = []
        for row in _rows_from_payload(payload):
            year = str(row.get("date") or "")
            try:
                t = datetime(int(year), 1, 1, tzinfo=timezone.utc)
            except ValueError:
                t = ingested_at
            indicator = row.get("indicator") or {}
            ind_id = indicator.get("id") if isinstance(indicator, dict) else str(indicator)
            events.append(
                WorldEvent(
                    id=f"worldbank:{ind_id}:{year}",
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=loc,
                    event_type="demographics.indicator",
                    payload={
                        "indicator": ind_id,
                        "indicator_name": indicator.get("value") if isinstance(indicator, dict) else None,
                        "country": (row.get("country") or {}).get("id") if isinstance(row.get("country"), dict) else "PH",
                        "date": year,
                        "value": row.get("value"),
                        "note": "PH country-level series; location is Manila centroid",
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.95),
                    temporal=Temporal(
                        source_time=t,
                        effective_time=t,
                        valid_from=t,
                        valid_until=None,
                        resolution="annual",
                    ),
                    information_cutoff=t,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = region or PHILIPPINES
        payload = None
        if live_requested("WORLDBANK_LIVE"):
            try:
                blocks = []
                for ind in INDICATORS:
                    blocks.append(
                        await http_get_json(
                            WB_URL.format(indicator=ind),
                            params={"format": "json", "per_page": 5},
                        )
                    )
                payload = {"responses": blocks}
            except Exception:
                payload = None
        if payload is None:
            payload = load_fixture(FIXTURE)
        events = self.normalize(payload)
        start, end = as_utc(window.start), as_utc(window.end)
        out = []
        for e in events:
            year = e.temporal.effective_time.year
            if start.year <= year <= end.year:
                out.append(e)
        return out
