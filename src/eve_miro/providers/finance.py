"""CoinGecko simple price. Public market indices only. OBSERVED."""

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
from eve_miro.core.world.temporal import utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json, live_requested
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
FIXTURE = "coingecko_simple_price.json"
IDS = "bitcoin,ethereum,ripple"


class CoinGeckoProvider:
    name = "coingecko"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="coingecko.simple_price",
            fields={"usd": "float", "usd_24h_change": "float"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="coingecko",
            dataset="simple_price",
            license="CoinGecko API terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.coingecko.com/",
            notes="Global public market prices. Location omitted (not a geographic series).",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested("COINGECKO_LIVE"),
            message="CoinGecko simple price",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="coingecko", dataset="simple_price", version="3", license="CoinGecko API terms")
        events: list[WorldEvent] = []
        stamp = ingested_at.strftime("%Y%m%dT%H%M%S")
        for coin, quote in (payload or {}).items():
            if not isinstance(quote, dict):
                continue
            events.append(
                WorldEvent(
                    id=f"coingecko:{coin}:{stamp}",
                    source=source,
                    observed_at=ingested_at,
                    ingested_at=ingested_at,
                    location=None,
                    entity=Entity(id=str(coin), type="instrument"),
                    event_type="market.price",
                    payload={
                        "id": coin,
                        "usd": quote.get("usd"),
                        "usd_24h_change": quote.get("usd_24h_change"),
                    },
                    provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
                    temporal=Temporal(
                        source_time=ingested_at,
                        effective_time=ingested_at,
                        valid_from=ingested_at,
                        valid_until=None,
                        resolution="snapshot",
                    ),
                    information_cutoff=ingested_at,
                )
            )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window, region or PHILIPPINES
        async def _live():
            return await http_get_json(
                PRICE_URL,
                params={"ids": IDS, "vs_currencies": "usd", "include_24hr_change": "true"},
            )

        payload = await fetch_live_or_fixture("COINGECKO_LIVE", FIXTURE, _live)
        return self.normalize(payload)
