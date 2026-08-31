"""Shared fetch helpers: fixture fallback, no invented live data."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from eve_miro.config import FIXTURES_DIR

_TRUTHY = {"1", "true", "True", "yes"}
_USER_AGENT = "eve-miro/1.0 (public-data adapters; research)"


def fixtures_enabled() -> bool:
    return os.environ.get("FIXTURES", "1") not in {"0", "false", "False"}


def live_requested(provider_flag: str | None = None) -> bool:
    """Live HTTP when FIXTURES=0, LIVE=1, or <PROVIDER>_LIVE=1. Tests keep FIXTURES=1."""
    if os.environ.get("LIVE", "0") in _TRUTHY:
        return True
    if provider_flag and os.environ.get(provider_flag, "0") in _TRUTHY:
        return True
    return not fixtures_enabled()


def load_fixture(name: str) -> Any:
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"fixture missing: {path}")
    return json.loads(path.read_text())


async def http_get_json(
    url: str,
    *,
    timeout: float = 20.0,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers=hdrs)
        response.raise_for_status()
        return response.json()


async def http_post_json(
    url: str,
    body: dict[str, Any],
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> Any:
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(url, json=body, headers=hdrs)
        response.raise_for_status()
        return response.json()

async def fetch_live_or_fixture(
    live_flag: str,
    fixture_name: str,
    live_factory,
    *,
    key_env: str | None = None,
) -> Any:
    """Use a fixture unless live is requested. Live HTTP must succeed or raise ProviderError."""
    from eve_miro.errors import ProviderError

    if not live_requested(live_flag):
        return load_fixture(fixture_name)
    if key_env and not (os.environ.get(key_env) or "").strip():
        raise ProviderError(f"{key_env} missing for live {live_flag} fetch")
    try:
        return await live_factory()
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"live {live_flag} fetch failed: {exc}") from exc
