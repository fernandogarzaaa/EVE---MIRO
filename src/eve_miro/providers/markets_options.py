"""yfinance options chains. OBSERVED.

Honesty note: free sources expose live chains only, with no history.
Historical chains cannot be backfilled from this source; IV history
accumulates in the reality ledger going forward instead.
"""

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
from eve_miro.core.world.temporal import utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, live_requested
from eve_miro.providers.markets_bars import _clean, configured_tickers
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FIXTURE = "markets_options.json"
LIVE_FLAG = "MARKETS_OPTIONS_LIVE"
MAX_EXPIRIES = 4


def download_chains(ticker: str, *, max_expiries: int = MAX_EXPIRIES) -> dict:
    """Blocking yfinance chain download; run inside asyncio.to_thread."""
    import yfinance as yf

    handle = yf.Ticker(ticker)
    chains = []
    for expiry in list(handle.options or [])[:max_expiries]:
        chain = handle.option_chain(expiry)
        chains.append(
            {
                "ticker": ticker,
                "expiry": expiry,
                "calls": [_contract_row("call", expiry, r) for _, r in chain.calls.iterrows()],
                "puts": [_contract_row("put", expiry, r) for _, r in chain.puts.iterrows()],
            }
        )
    return {"ticker": ticker, "chains": chains}


def _contract_row(option_type: str, expiry: str, row) -> dict:
    return {
        "expiry": expiry,
        "option_type": option_type,
        "strike": _clean(row.get("strike")),
        "last_price": _clean(row.get("lastPrice")),
        "bid": _clean(row.get("bid")),
        "ask": _clean(row.get("ask")),
        "volume": _clean(row.get("volume")),
        "open_interest": _clean(row.get("openInterest")),
        "implied_volatility": _clean(row.get("impliedVolatility")),
        "in_the_money": bool(row.get("inTheMoney")),
    }


async def _live_payload() -> dict:
    chains = []
    for ticker in configured_tickers():
        payload = await asyncio.to_thread(download_chains, ticker)
        chains.extend(payload["chains"])
    return {"chains": chains}


class MarketsOptionsProvider:
    name = "markets_options"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="markets_options.chain",
            fields={
                "expiry": "str",
                "option_type": "str",
                "strike": "float",
                "implied_volatility": "float",
                "volume": "float",
                "open_interest": "float",
            },
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="markets_options",
            dataset="yfinance.options_chain",
            license="Yahoo Finance terms",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://finance.yahoo.com/",
            notes="Live chains only; free sources carry no historical chains. IV history accumulates in the ledger going forward.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested(LIVE_FLAG),
            message="yfinance options chains",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="markets_options", dataset="yfinance.options_chain", version="v8", license="Yahoo Finance terms")
        events: list[WorldEvent] = []
        for chain in (payload or {}).get("chains") or []:
            ticker = str(chain.get("ticker") or "").upper()
            for side in ("calls", "puts"):
                for contract in chain.get(side) or []:
                    strike = _clean(contract.get("strike"))
                    option_type = contract.get("option_type") or ("call" if side == "calls" else "put")
                    expiry = str(contract.get("expiry") or chain.get("expiry") or "")
                    if not ticker or strike is None:
                        continue
                    events.append(
                        WorldEvent(
                            id=f"markets_options:{ticker}:{expiry}:{option_type}:{strike:g}",
                            source=source,
                            observed_at=ingested_at,
                            ingested_at=ingested_at,
                            location=None,
                            entity=Entity(id=f"{ticker}:{expiry}:{strike:g}:{option_type}", type="instrument"),
                            event_type="market.options_chain",
                            payload={
                                "ticker": ticker,
                                "expiry": expiry,
                                "option_type": option_type,
                                "strike": strike,
                                "last_price": _clean(contract.get("last_price")),
                                "bid": _clean(contract.get("bid")),
                                "ask": _clean(contract.get("ask")),
                                "volume": _clean(contract.get("volume")),
                                "open_interest": _clean(contract.get("open_interest")),
                                "implied_volatility": _clean(contract.get("implied_volatility")),
                                "in_the_money": bool(contract.get("in_the_money")),
                            },
                            provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.85),
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
        payload = await fetch_live_or_fixture(LIVE_FLAG, FIXTURE, _live_payload)
        return self.normalize(payload)
