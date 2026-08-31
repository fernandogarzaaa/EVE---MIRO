"""Data providers. Live adapters for Open-Meteo and USGS; honest stubs otherwise."""

from eve_miro.providers.protocol import DataProvider, DataSchema, ProviderHealth, ProviderProvenance, TimeWindow
from eve_miro.providers.registry import all_providers, get_provider

__all__ = [
    "DataProvider",
    "DataSchema",
    "ProviderHealth",
    "ProviderProvenance",
    "TimeWindow",
    "all_providers",
    "get_provider",
]
