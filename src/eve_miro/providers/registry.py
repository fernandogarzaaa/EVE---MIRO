"""Named provider registry used by ingest and /health."""

from __future__ import annotations

from eve_miro.providers.earthquakes import USGSProvider
from eve_miro.providers.protocol import DataProvider
from eve_miro.providers.stubs import (
    AISStreamProvider,
    CelestrakProvider,
    CoinGeckoProvider,
    GDACSProvider,
    GDELTProvider,
    NASAProvider,
    OpenSkyProvider,
    OSMProvider,
    WorldBankProvider,
)
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
}


def get_provider(name: str) -> DataProvider:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown provider {name}") from exc


def all_providers() -> dict[str, DataProvider]:
    return dict(_PROVIDERS)
