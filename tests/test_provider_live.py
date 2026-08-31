"""Live provider fetch uses HTTP when requested and fail-closes on errors. Offline mocks only."""

from __future__ import annotations

import pytest

from eve_miro.errors import ProviderError
from eve_miro.providers.ais import AISStreamProvider
from eve_miro.providers.common import load_fixture
from eve_miro.providers.news import GDELTProvider
from eve_miro.providers.protocol import TimeWindow
from eve_miro.providers.weather import OpenMeteoProvider

WINDOW = TimeWindow(start="2024-11-01T00:00:00Z", end="2024-11-01T06:00:00Z")


@pytest.mark.asyncio
async def test_openmeteo_live_fetch_uses_mocked_http(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("FIXTURES", "0")
    payload = load_fixture("openmeteo_manila_archive.json")
    seen = {}

    async def fake_get(url, **kwargs):
        seen["url"] = url
        return payload

    monkeypatch.setattr("eve_miro.providers.weather.http_get_json", fake_get)
    events = await OpenMeteoProvider(mode="archive").fetch(WINDOW)
    assert seen["url"]
    assert "archive-api.open-meteo.com" in seen["url"]
    assert events
    assert events[0].payload.get("wind_speed_10m") is not None


@pytest.mark.asyncio
async def test_openmeteo_live_http_failure_raises(monkeypatch):
    monkeypatch.setenv("OPENMETEO_LIVE", "1")
    monkeypatch.setenv("FIXTURES", "1")

    async def boom(*_a, **_k):
        raise RuntimeError("open-meteo unavailable")

    monkeypatch.setattr("eve_miro.providers.weather.http_get_json", boom)
    with pytest.raises(ProviderError, match="OPENMETEO_LIVE"):
        await OpenMeteoProvider(mode="archive").fetch(WINDOW)


@pytest.mark.asyncio
async def test_gdelt_live_fetch_uses_mocked_http(monkeypatch):
    monkeypatch.setenv("GDELT_LIVE", "1")
    payload = load_fixture("gdelt_ph_articles.json")
    seen = {}

    async def fake_get(url, **kwargs):
        seen["url"] = url
        seen["params"] = kwargs.get("params")
        return payload

    monkeypatch.setattr("eve_miro.providers.news.http_get_json", fake_get)
    events = await GDELTProvider().fetch(WINDOW)
    assert seen["url"]
    assert "gdeltproject.org" in seen["url"]
    assert events
    assert all(e.event_type == "news.article" for e in events)


@pytest.mark.asyncio
async def test_ais_live_missing_key_fail_closed(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="AISSTREAM_API_KEY"):
        await AISStreamProvider().fetch(WINDOW)
