"""VIX index via yfinance daily bars. OBSERVED."""

from __future__ import annotations

import asyncio
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
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, live_requested
from eve_miro.providers.markets_bars import _clean, download_history
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FIXTURE = "market_vol.json"
LIVE_FLAG = "MARKET_VOL_LIVE"
SYMBOL = "^VIX"


async def _live_payload() -> dict:
    series = await asyncio.to_thread(download_history, SYMBOL, period="1mo", interval="1d")
    return {"series": [series]}


class MarketVolProvider:
    name = "market_vol"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="market_vol.vix",
            fields={"vix": "float", "date": "str"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="market_vol",
            dataset="yfinance.vix_daily",
            license="Yahoo Finance terms; Cboe VIX methodology",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://www.cboe.com/indices/vix/",
            notes="Cboe Volatility Index daily closes via yfinance. Location omitted (not a geographic series).",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested(LIVE_FLAG),
            message="VIX daily closes",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="market_vol", dataset="yfinance.vix_daily", version="v8", license="Yahoo Finance terms")
        events: list[WorldEvent] = []
        for series in (payload or {}).get("series") or []:
            for bar in series.get("bars") or []:
                t = as_utc(bar.get("date") or ingested_at)
                vix = _clean(bar.get("close"))
                if vix is None:
                    continue
                events.append(
                    WorldEvent(
                        id=f"market_vol:VIX:{t.strftime('%Y%m%d')}",
                        source=source,
                        observed_at=t,
                        ingested_at=ingested_at,
                        location=None,
                        entity=Entity(id="VIX", type="index"),
                        event_type="market.iv_index",
                        payload={
                            "symbol": "VIX",
                            "date": t.date().isoformat(),
                            "vix": vix,
                        },
                        provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.9),
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
        payload = await fetch_live_or_fixture(LIVE_FLAG, FIXTURE, _live_payload)
        return self.normalize(payload)
