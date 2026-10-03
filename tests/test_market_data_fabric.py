"""Phase 1 market-data fabric: providers, registry, projector snapshot."""

from __future__ import annotations

import pytest

from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.markets import build_market_snapshot
from eve_miro.core.world.projector import project_world_state
from eve_miro.errors import ProviderError
from eve_miro.providers.common import load_fixture
from eve_miro.providers.macro_fred import MacroFREDProvider
from eve_miro.providers.market_vol import MarketVolProvider
from eve_miro.providers.markets_bars import MarketsBarsProvider
from eve_miro.providers.markets_options import MarketsOptionsProvider
from eve_miro.providers.news_markets import GDELTMarketsProvider
from eve_miro.providers.protocol import TimeWindow
from eve_miro.providers.registry import all_providers

WINDOW = TimeWindow(start="2026-10-01T00:00:00Z", end="2026-10-03T00:00:00Z")


def _observed(events, event_type):
    assert events
    assert all(e.kind is ProvenanceKind.OBSERVED for e in events)
    assert all(e.event_type == event_type for e in events)
    assert all(e.kind is not ProvenanceKind.SIMULATED for e in events)


def test_markets_bars_fixture_normalizes():
    events = MarketsBarsProvider().normalize(load_fixture("markets_bars.json"))
    _observed(events, "market.bar")
    tickers = {e.entity.id for e in events}
    assert {"SPY", "AAPL"} <= tickers
    assert all(e.entity.type == "instrument" for e in events)
    assert all(e.location is None for e in events)
    for e in events:
        assert isinstance(e.payload["close"], (int, float))
        assert e.information_cutoff is not None


def test_markets_bars_fixture_fetch_path():
    async def go():
        return await MarketsBarsProvider().fetch(WINDOW)
    import asyncio
    events = asyncio.run(go())
    assert events
    assert all(e.event_type == "market.bar" for e in events)


def test_markets_options_fixture_normalizes():
    events = MarketsOptionsProvider().normalize(load_fixture("markets_options.json"))
    _observed(events, "market.options_chain")
    sides = {e.payload["option_type"] for e in events}
    assert sides == {"call", "put"}
    assert all(e.payload["implied_volatility"] is not None for e in events)
    assert all(e.payload["expiry"] in {"2026-10-16", "2026-12-18"} for e in events)
    assert all(e.entity.type == "instrument" for e in events)


def test_macro_fred_fixture_normalizes():
    events = MacroFREDProvider().normalize(load_fixture("macro_fred.json"))
    _observed(events, "market.macro")
    series = {e.payload["series_id"] for e in events}
    assert series == {"DGS10", "CPIAUCSL", "UNRATE", "FEDFUNDS"}
    dgs10 = [e for e in events if e.payload["series_id"] == "DGS10"]
    assert dgs10[-1].payload["value"] == 4.19


def test_macro_fred_live_without_key_fail_closed(monkeypatch):
    monkeypatch.setenv("MACRO_FRED_LIVE", "1")
    monkeypatch.setenv("FIXTURES", "0")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    import asyncio
    with pytest.raises(ProviderError, match="FRED_API_KEY"):
        asyncio.run(MacroFREDProvider().fetch(WINDOW))


def test_market_vol_fixture_normalizes():
    events = MarketVolProvider().normalize(load_fixture("market_vol.json"))
    _observed(events, "market.iv_index")
    assert all(e.payload["symbol"] == "VIX" for e in events)
    assert all(e.payload["vix"] > 0 for e in events)


def test_gdelt_markets_fixture_normalizes():
    events = GDELTMarketsProvider().normalize(load_fixture("gdelt_markets_articles.json"))
    _observed(events, "market.news")
    assert len(events) == 3
    for e in events:
        assert e.location is None
        assert "persons" not in e.payload
        assert e.payload["title"]


def test_registry_includes_market_providers():
    providers = all_providers()
    for name in ("markets_bars", "markets_options", "macro_fred", "market_vol", "gdelt_markets"):
        assert name in providers, f"{name} missing from registry"


def test_provider_health_reports_fixtures():
    import asyncio
    for provider in (
        MarketsBarsProvider(), MarketsOptionsProvider(), MacroFREDProvider(),
        MarketVolProvider(), GDELTMarketsProvider(),
    ):
        h = asyncio.run(provider.health())
        assert h.available
        assert h.using_fixtures


def test_market_snapshot_builder():
    events = []
    events += MarketsBarsProvider().normalize(load_fixture("markets_bars.json"))
    events += MarketsOptionsProvider().normalize(load_fixture("markets_options.json"))
    events += MarketVolProvider().normalize(load_fixture("market_vol.json"))
    events += MacroFREDProvider().normalize(load_fixture("macro_fred.json"))
    events += GDELTMarketsProvider().normalize(load_fixture("gdelt_markets_articles.json"))
    snapshot = build_market_snapshot(events)
    spy = snapshot["tickers"]["SPY"]
    assert spy["latest_close"] > 0
    assert spy["bars_n"] == 25
    assert spy["return_1d"] is not None
    assert spy["return_20d"] is not None
    assert spy["realized_vol_20d"] is not None and spy["realized_vol_20d"] >= 0
    assert spy["options"]["contracts_n"] == 12
    assert spy["options"]["iv_near_term_mean"] is not None
    assert snapshot["vix"]["latest"] > 0
    assert snapshot["macro"]["DGS10"]["value"] == 4.19
    assert snapshot["news"]["count"] == 3


def test_projector_folds_market_snapshot():
    events = []
    events += MarketsBarsProvider().normalize(load_fixture("markets_bars.json"))
    events += MarketVolProvider().normalize(load_fixture("market_vol.json"))
    state = project_world_state(
        "w1",
        events,
        at="2026-10-03T00:00:00Z",
        information_cutoff="2026-10-03T00:00:00Z",
    )
    indicators = state.economy.indicators
    assert "market" in indicators
    assert "market_snapshot" in indicators
    assert indicators["market_snapshot"]["tickers"]["AAPL"]["latest_close"] > 0
