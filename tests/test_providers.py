from eve_miro.core.world.events import ProvenanceKind
from eve_miro.providers.earthquakes import USGSProvider
from eve_miro.providers.weather import OpenMeteoProvider


def test_openmeteo_archive_fixture_is_observed():
    payload = __import__("json").loads(
        (__import__("pathlib").Path("datasets/fixtures/openmeteo_manila_archive.json")).read_text()
    ) if False else None
    provider = OpenMeteoProvider(mode="archive")
    from eve_miro.providers.common import load_fixture

    events = provider.normalize(load_fixture("openmeteo_manila_archive.json"))
    assert events
    assert all(e.kind is ProvenanceKind.OBSERVED for e in events)
    assert events[0].payload["wind_speed_10m"] is not None
    assert events[0].location.lat > 14


def test_openmeteo_forecast_fixture_is_forecast():
    from eve_miro.providers.common import load_fixture

    events = OpenMeteoProvider(mode="forecast").normalize(load_fixture("openmeteo_manila_forecast.json"))
    assert events
    assert all(e.kind is ProvenanceKind.FORECAST for e in events)


def test_usgs_fixture_is_observed_and_in_ph_bbox():
    from eve_miro.providers.common import load_fixture
    from eve_miro.config import PHILIPPINES

    events = USGSProvider().normalize(load_fixture("usgs_philippines.json"))
    assert events
    assert all(e.kind is ProvenanceKind.OBSERVED for e in events)
    assert all(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert any(e.payload.get("mag") for e in events)
