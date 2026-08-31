"""Shared region, bbox, and provider cadence configuration."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, Field

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
FIXTURES_DIR = REPO_ROOT / "datasets" / "fixtures"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
TRACES_DIR = REPO_ROOT / "data" / "traces"


class Region(BaseModel):
    """Geographic bounding box. Default domain is the Philippines."""

    name: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon


PHILIPPINES = Region(name="philippines", min_lat=4.2, max_lat=21.2, min_lon=116.5, max_lon=127.0)
METRO_MANILA = Region(name="metro_manila", min_lat=14.35, max_lat=14.80, min_lon=120.90, max_lon=121.15)
MANILA_LAT = 14.5995
MANILA_LON = 120.9842

# Different clocks: do not poll every provider every second.
PROVIDER_INTERVALS: dict[str, timedelta] = {
    "openmeteo": timedelta(hours=1),
    "usgs": timedelta(minutes=15),
    "opensky": timedelta(seconds=30),
    "aisstream": timedelta(seconds=30),
    "gdacs": timedelta(minutes=10),
    "gdelt": timedelta(minutes=15),
    "osm": timedelta(hours=24),
    "nasa": timedelta(hours=6),
    "celestrak": timedelta(hours=6),
    "coingecko": timedelta(minutes=5),
    "worldbank": timedelta(days=30),
    "spaceweather": timedelta(minutes=5),
}

DEFAULT_POPULATION_TEST = 200
DEFAULT_POPULATION_SCENARIO = 1000


class TimeWindow(BaseModel):
    start: str
    end: str
    region: str = "philippines"


class Settings(BaseModel):
    fixtures: bool = Field(default=True)
    database_url: str = ""
    traces_dir: Path = TRACES_DIR
