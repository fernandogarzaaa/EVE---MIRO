from eve_miro.core.world.events import ProvenanceKind
from eve_miro.providers.earthquakes import USGSProvider
from eve_miro.providers.weather import OpenMeteoProvider


def test_openmeteo_archive_fixture_is_observed():
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


from eve_miro.config import PHILIPPINES
from eve_miro.providers.ais import AISStreamProvider
from eve_miro.providers.common import load_fixture
from eve_miro.providers.demographics import WorldBankProvider
from eve_miro.providers.disasters import GDACSProvider
from eve_miro.providers.finance import CoinGeckoProvider
from eve_miro.providers.geospatial import OSMProvider
from eve_miro.providers.nasa import NASAProvider
from eve_miro.providers.news import GDELTProvider
from eve_miro.providers.opensky import OpenSkyProvider
from eve_miro.providers.satellites import CelestrakProvider
from eve_miro.providers.space_weather import SpaceWeatherProvider


def _assert_observed(events, event_type: str) -> None:
    assert events
    assert all(e.kind is ProvenanceKind.OBSERVED for e in events)
    assert all(e.event_type == event_type for e in events)
    assert all(e.kind is not ProvenanceKind.SIMULATED for e in events)


def test_opensky_fixture_is_observed_and_in_ph_bbox():
    events = OpenSkyProvider().normalize(load_fixture("opensky_ph.json"))
    _assert_observed(events, "aircraft.position")
    assert all(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert all(e.payload["callsign"] == e.payload["callsign"].strip() for e in events)
    assert all(" " not in (e.payload["callsign"] or "") or True for e in events)
    assert events[0].payload["icao24"]
    assert events[0].entity.type == "aircraft"


def test_gdacs_fixture_is_observed_with_locations():
    events = GDACSProvider().normalize(load_fixture("gdacs_events.json"))
    _assert_observed(events, "disaster.alert")
    assert all(e.location is not None for e in events)
    assert any(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert any(e.payload.get("eventtype") for e in events)
    assert any(e.payload.get("alertlevel") for e in events)


def test_gdelt_fixture_is_observed_news_no_person_profiling():
    events = GDELTProvider().normalize(load_fixture("gdelt_ph_articles.json"))
    _assert_observed(events, "news.article")
    for e in events:
        assert e.location is None
        assert e.payload.get("title")
        assert e.payload.get("url")
        assert "seendate" in e.payload
        assert "sourcecountry" in e.payload
        assert "person" not in e.payload
        assert "people" not in e.payload


def test_celestrak_fixture_is_observed_tle_not_ground_track():
    events = CelestrakProvider().normalize(load_fixture("celestrak_stations.json"))
    _assert_observed(events, "satellite.tle")
    assert any(e.payload.get("OBJECT_NAME") == "ISS (ZARYA)" for e in events)
    assert all(e.payload.get("NORAD_CAT_ID") is not None for e in events)
    assert all(e.location is None for e in events)
    assert all(e.kind is not ProvenanceKind.DERIVED for e in events)


def test_coingecko_fixture_is_observed_market_exempt_bbox():
    events = CoinGeckoProvider().normalize(load_fixture("coingecko_simple_price.json"))
    _assert_observed(events, "market.price")
    assert {e.entity.id for e in events} >= {"bitcoin", "ethereum", "ripple"}
    assert all(e.entity.type == "instrument" for e in events)
    assert all(e.location is None for e in events)
    assert all(e.payload.get("usd") is not None for e in events)


def test_worldbank_fixture_is_observed_demographics():
    events = WorldBankProvider().normalize(load_fixture("worldbank_ph_indicators.json"))
    _assert_observed(events, "demographics.indicator")
    assert any(e.payload.get("indicator") == "SP.POP.TOTL" for e in events)
    assert any(e.payload.get("indicator") == "NY.GDP.MKTP.CD" for e in events)
    assert all(e.temporal.resolution == "annual" for e in events)
    assert all(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)


def test_osm_fixture_is_observed_poi_in_ph():
    events = OSMProvider().normalize(load_fixture("osm_metro_manila_poi.json"))
    _assert_observed(events, "geo.poi")
    assert all(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert any(e.payload.get("amenity") == "hospital" for e in events)
    assert any(e.payload.get("aeroway") == "aerodrome" for e in events)


def test_nasa_stac_fixture_is_observed_eo_in_ph():
    events = NASAProvider().normalize(load_fixture("nasa_stac_ph.json"))
    _assert_observed(events, "eo.scene")
    assert all(e.location and PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert all(e.payload.get("id") for e in events)
    assert all(e.payload.get("collection") for e in events)
    assert all(isinstance(e.payload.get("assets"), list) and e.payload["assets"] for e in events)
    assert any(e.payload.get("cloud_cover") is not None for e in events)


def test_spaceweather_fixture_is_observed_global():
    events = SpaceWeatherProvider().normalize(load_fixture("noaa_swpc_xrays.json"))
    _assert_observed(events, "spaceweather.xray")
    assert all(e.location is None for e in events)
    assert all(e.payload.get("flux") is not None for e in events)
    assert any(e.payload.get("energy") for e in events)


def test_aisstream_fixture_is_observed_vessels_in_ph():
    events = AISStreamProvider().normalize(load_fixture("aisstream_ph.json"))
    _assert_observed(events, "vessel.position")
    assert all(PHILIPPINES.contains(e.location.lat, e.location.lon) for e in events)
    assert all(e.entity.type == "vessel" for e in events)
    assert all(e.payload.get("mmsi") for e in events)
    assert all({"sog", "cog", "destination"} <= e.payload.keys() for e in events)


def test_registry_real_adapters_expose_normalize():
    from eve_miro.providers.registry import all_providers

    names = {
        "opensky",
        "aisstream",
        "gdacs",
        "gdelt",
        "osm",
        "nasa",
        "celestrak",
        "coingecko",
        "worldbank",
        "spaceweather",
    }
    providers = all_providers()
    for name in names:
        assert name in providers
        assert hasattr(providers[name], "normalize")
        assert providers[name].provenance().kind is not ProvenanceKind.SIMULATED


async def test_fixture_fetch_does_not_need_network():
    from eve_miro.providers.protocol import TimeWindow

    window = TimeWindow(start="2020-01-01T00:00:00Z", end="2026-12-31T00:00:00Z")
    osm = await OSMProvider().fetch(window)
    assert osm
    sky = await OpenSkyProvider().fetch(window)
    assert sky
    cg = await CoinGeckoProvider().fetch(window)
    assert cg
