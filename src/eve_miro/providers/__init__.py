"""Data providers. Live public-data adapters. FIXTURES=1 is offline; live HTTP fail-closes. StubProvider is a test double, not registered."""

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
