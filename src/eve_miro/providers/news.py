"""GDELT 2.0 document list (Philippines query). Article metadata only; no person profiling."""

from __future__ import annotations

from datetime import datetime, timezone

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json, live_requested
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FIXTURE = "gdelt_ph_articles.json"


def _parse_seendate(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    text = value.strip()
    if len(text) >= 15 and text[8] == "T":
        try:
            return datetime.strptime(text.replace("Z", ""), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return as_utc(text)
    except ValueError:
        return fallback


class GDELTProvider:
    name = "gdelt"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="gdelt.artlist",
            fields={"title": "str", "url": "str", "seendate": "str", "sourcecountry": "str"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="gdelt",
            dataset="doc.artlist",
            license="GDELT terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.gdeltproject.org/",
            notes="Article metadata for a Philippines query. No named-person profiling. Live last-15-min CSV is not downloaded.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("GDELT_LIVE"),
            message="GDELT DOC ArtList (Philippines)",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="gdelt", dataset="doc.artlist", version="2.0", license="GDELT")
        events: list[WorldEvent] = []
        for art in payload.get("articles") or []:
            title = art.get("title") or ""
            url = art.get("url") or ""
            seendate = art.get("seendate")
            t = _parse_seendate(seendate, ingested_at)
            eid = url or f"gdelt:{t.strftime('%Y%m%dT%H%M%S')}:{title[:40]}"
            events.append(
                WorldEvent(
                    id=f"gdelt:{eid}"[:240],
                    source=source,
                    observed_at=t,
                    ingested_at=ingested_at,
                    location=None,
                    event_type="news.article",
                    payload={
                        "title": title,
                        "url": url,
                        "seendate": seendate,
                        "sourcecountry": art.get("sourcecountry"),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.8),
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
        _ = window, region or PHILIPPINES
        async def _live():
            return await http_get_json(
                DOC_URL,
                params={
                    "query": "Philippines",
                    "mode": "ArtList",
                    "maxrecords": 10,
                    "format": "json",
                },
                timeout=20.0,
            )

        payload = await fetch_live_or_fixture("GDELT_LIVE", FIXTURE, _live)
        return self.normalize(payload)
