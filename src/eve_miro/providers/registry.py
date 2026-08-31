"""Named provider registry used by ingest and /health."""

from __future__ import annotations

from eve_miro.providers.ais import AISStreamProvider
from eve_miro.providers.demographics import WorldBankProvider
from eve_miro.providers.disasters import GDACSProvider
from eve_miro.providers.earthquakes import USGSProvider
from eve_miro.providers.finance import CoinGeckoProvider
from eve_miro.providers.geospatial import OSMProvider
from eve_miro.providers.nasa import NASAProvider
from eve_miro.providers.news import GDELTProvider
from eve_miro.providers.opensky import OpenSkyProvider
from eve_miro.providers.protocol import DataProvider
from eve_miro.providers.satellites import CelestrakProvider
from eve_miro.providers.space_weather import SpaceWeatherProvider
from eve_miro.providers.weather import OpenMeteoProvider

_PROVIDERS: dict[str, DataProvider] = {
    "openmeteo": OpenMeteoProvider(mode="archive"),
    "openmeteo_forecast": OpenMeteoProvider(mode="forecast"),
    "usgs": USGSProvider(),
    "opensky": OpenSkyProvider(),
    "aisstream": AISStreamProvider(),
    "gdacs": GDACSProvider(),
    "gdelt": GDELTProvider(),
    "osm": OSMProvider(),
    "nasa": NASAProvider(),
    "celestrak": CelestrakProvider(),
    "coingecko": CoinGeckoProvider(),
    "worldbank": WorldBankProvider(),
    "spaceweather": SpaceWeatherProvider(),
}


def get_provider(name: str) -> DataProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown provider {name}") from exc


def all_providers() -> dict[str, DataProvider]:
    return dict(_PROVIDERS)
