"""yfinance OHLCV bars per ticker. Daily bars plus intraday where the free window allows. OBSERVED."""

from __future__ import annotations

import asyncio
import math
import os
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
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FIXTURE = "markets_bars.json"
LIVE_FLAG = "MARKETS_BARS_LIVE"
TICKERS_ENV = "MARKETS_TICKERS"
DEFAULT_TICKERS = ("SPY", "QQQ", "AAPL", "MSFT")
DAILY_PERIOD = "3mo"
DAILY_INTERVAL = "1d"
INTRADAY_PERIOD = "5d"
INTRADAY_INTERVAL = "1h"


def configured_tickers() -> tuple[str, ...]:
    raw = (os.environ.get(TICKERS_ENV) or "").strip()
    if not raw:
        return DEFAULT_TICKERS
    return tuple(t.strip().upper() for t in raw.split(",") if t.strip())


def _clean(value):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def download_history(ticker: str, *, period: str, interval: str) -> dict:
    """Blocking yfinance download; run inside asyncio.to_thread. Returns the fixture-shaped payload."""
    import yfinance as yf

    frame = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    bars = []
    for ts, row in frame.iterrows():
        bars.append(
            {
                "date": as_utc(ts.to_pydatetime()).isoformat(),
                "open": _clean(row.get("Open")),
                "high": _clean(row.get("High")),
                "low": _clean(row.get("Low")),
                "close": _clean(row.get("Close")),
                "volume": _clean(row.get("Volume")),
            }
        )
    return {"ticker": ticker, "interval": interval, "currency": "USD", "bars": bars}


async def _live_payload() -> dict:
    series = []
    for ticker in configured_tickers():
        daily = await asyncio.to_thread(download_history, ticker, period=DAILY_PERIOD, interval=DAILY_INTERVAL)
        intraday = await asyncio.to_thread(download_history, ticker, period=INTRADAY_PERIOD, interval=INTRADAY_INTERVAL)
        series.append(daily)
        if intraday["bars"]:
            series.append(intraday)
    return {"series": series}


class MarketsBarsProvider:
    name = "markets_bars"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="markets_bars.ohlcv",
            fields={"open": "float", "high": "float", "low": "float", "close": "float", "volume": "float", "interval": "str"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="markets_bars",
            dataset="yfinance.ohlcv",
            license="Yahoo Finance terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://finance.yahoo.com/",
            notes="Daily bars (3mo) plus 1h intraday bars (5d, free-window limit) per ticker. Location omitted (not a geographic series).",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested(LIVE_FLAG),
            message="yfinance OHLCV bars",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="markets_bars", dataset="yfinance.ohlcv", version="v8", license="Yahoo Finance terms")
        events: list[WorldEvent] = []
        for series in (payload or {}).get("series") or []:
            ticker = str(series.get("ticker") or "").upper()
            interval = str(series.get("interval") or "")
            if not ticker:
                continue
            for bar in series.get("bars") or []:
                t = as_utc(bar.get("date") or ingested_at)
                close = _clean(bar.get("close"))
                events.append(
                    WorldEvent(
                        id=f"markets_bars:{ticker}:{interval}:{t.strftime('%Y%m%dT%H%M%S')}",
                        source=source,
                        observed_at=t,
                        ingested_at=ingested_at,
                        location=None,
                        entity=Entity(id=ticker, type="instrument"),
                        event_type="market.bar",
                        payload={
                            "ticker": ticker,
                            "interval": interval,
                            "currency": series.get("currency") or "USD",
                            "open": _clean(bar.get("open")),
                            "high": _clean(bar.get("high")),
                            "low": _clean(bar.get("low")),
                            "close": close,
                            "volume": _clean(bar.get("volume")),
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
