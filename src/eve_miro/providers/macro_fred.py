"""FRED macro series: 10y yield, CPI, unemployment, fed funds. OBSERVED.

Fail-closed: live mode requires FRED_API_KEY (free key from stlouisfed.org).
CI runs on the recorded fixture.

Pre-fetched file mode: when FRED_MACRO_JSON points at a JSON file of the form
{"DGS10": [{"date": "2026-10-01", "value": "5.24"}, ...], ...}, the file is
used instead of the API. This exists for scheduled runs whose FRED credential
lives outside the process environment (e.g. behind a credential vault): a
local step pre-fetches observations into the file and the provider reads it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import (
    Entity,
    Provenance,
    ProvenanceKind,
    Source,
    Temporal,
    WorldEvent,
)
from eve_miro.core.world.temporal import as_utc, utcnow
from eve_miro.providers.common import fetch_live_or_fixture, fixtures_enabled, http_get_json, live_requested
from eve_miro.providers.protocol import DataSchema, ProviderHealth, ProviderProvenance, TimeWindow

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FIXTURE = "macro_fred.json"
LIVE_FLAG = "MACRO_FRED_LIVE"
KEY_ENV = "FRED_API_KEY"
FILE_ENV = "FRED_MACRO_JSON"

SERIES = {
    "DGS10": {"title": "10-Year Treasury Constant Maturity Rate", "units": "percent"},
    "CPIAUCSL": {"title": "Consumer Price Index for All Urban Consumers", "units": "index"},
    "UNRATE": {"title": "Unemployment Rate", "units": "percent"},
    "FEDFUNDS": {"title": "Effective Federal Funds Rate", "units": "percent"},
}


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_file_payload(path: str) -> dict:
    """Parse a pre-fetched macro JSON file into provider payload shape.

    Schema: {"<series_id>": [{"date": "YYYY-MM-DD", "value": "<num>"}, ...], ...}.
    Observation values may be strings (FRED's native form, "." for missing) or
    numbers; unparseable values are dropped at normalize time.

    Fail-closed: raises ValueError on corrupt content. The caller decides
    whether that is fatal (provider.fetch) or a loud soft skip (the weekly
    accumulation run).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ValueError(
            f"{path}: top level must be a non-empty object mapping series id to observations"
        )
    series: dict[str, dict] = {}
    for series_id, obs_list in raw.items():
        if not isinstance(series_id, str) or not series_id.strip():
            raise ValueError(f"{path}: series id must be a non-empty string, got {series_id!r}")
        if not isinstance(obs_list, list) or not obs_list:
            raise ValueError(f"{path}: {series_id!r} observations must be a non-empty list")
        observations = []
        for obs in obs_list:
            if not isinstance(obs, dict) or "date" not in obs or "value" not in obs:
                raise ValueError(
                    f"{path}: {series_id!r} each observation needs 'date' and 'value'"
                )
            observations.append({"date": str(obs["date"]), "value": obs["value"]})
        meta = SERIES.get(series_id, {})
        series[series_id] = {
            "title": meta.get("title", series_id),
            "units": meta.get("units", ""),
            "observations": observations,
        }
    return {"series": series}


async def _live_payload() -> dict:
    api_key = (os.environ.get(KEY_ENV) or "").strip()
    out: dict[str, dict] = {}
    for series_id, meta in SERIES.items():
        payload = await http_get_json(
            FRED_URL,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 12,
            },
            timeout=20.0,
        )
        out[series_id] = {
            "title": meta["title"],
            "units": meta["units"],
            "observations": [
                {"date": obs.get("date"), "value": obs.get("value")}
                for obs in (payload or {}).get("observations") or []
            ],
        }
    return {"series": out}


class MacroFREDProvider:
    name = "macro_fred"

    def schema(self) -> DataSchema:
        return DataSchema(
            name="macro_fred.series",
            fields={"series_id": "str", "date": "str", "value": "float", "units": "str"},
            provenance_kind=ProvenanceKind.OBSERVED,
        )

    def provenance(self) -> ProviderProvenance:
        return ProviderProvenance(
            provider="macro_fred",
            dataset="fred.series_observations",
            license="FRED terms of use",
            kind=ProvenanceKind.OBSERVED,
            homepage="https://fred.stlouisfed.org/",
            notes="Monthly/quarterly macro series. Live mode needs a free FRED_API_KEY; "
            "fail-closed without it. FRED_MACRO_JSON points at a pre-fetched JSON file "
            "and takes precedence over the API key.",
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            available=True,
            interval_seconds=PROVIDER_INTERVALS[self.name].total_seconds(),
            using_fixtures=fixtures_enabled() and not live_requested(LIVE_FLAG),
            message="FRED macro series",
        )

    def normalize(self, payload: dict, *, ingested_at: datetime | None = None) -> list[WorldEvent]:
        ingested_at = ingested_at or utcnow()
        source = Source(provider="macro_fred", dataset="fred.series_observations", version="v1", license="FRED terms of use")
        events: list[WorldEvent] = []
        for series_id, series in ((payload or {}).get("series") or {}).items():
            meta = SERIES.get(series_id, {})
            for obs in series.get("observations") or []:
                t = as_utc(obs.get("date") or ingested_at)
                value = _to_float(obs.get("value"))
                if value is None:
                    continue
                events.append(
                    WorldEvent(
                        id=f"macro_fred:{series_id}:{t.strftime('%Y%m%d')}",
                        source=source,
                        observed_at=t,
                        ingested_at=ingested_at,
                        location=None,
                        entity=Entity(id=series_id, type="macro_series"),
                        event_type="market.macro",
                        payload={
                            "series_id": series_id,
                            "title": series.get("title") or meta.get("title"),
                            "units": series.get("units") or meta.get("units"),
                            "date": t.date().isoformat(),
                            "value": value,
                        },
                        provenance=Provenance(kind=ProvenanceKind.OBSERVED, raw=True, confidence=0.95),
                        temporal=Temporal(
                            source_time=t,
                            effective_time=t,
                            valid_from=t,
                            valid_until=None,
                            resolution="event",
                        ),
                        information_cutoff=t,
                    )
                )
        return events

    async def fetch(self, window: TimeWindow, region: Region | None = None) -> list[WorldEvent]:
        _ = window, region or PHILIPPINES
        file_path = (os.environ.get(FILE_ENV) or "").strip()
        if file_path:
            from eve_miro.errors import ProviderError

            try:
                return self.normalize(read_file_payload(file_path))
            except (OSError, ValueError) as exc:
                raise ProviderError(f"{FILE_ENV} unreadable: {exc}") from exc
        payload = await fetch_live_or_fixture(LIVE_FLAG, FIXTURE, _live_payload, key_env=KEY_ENV)
        return self.normalize(payload)
