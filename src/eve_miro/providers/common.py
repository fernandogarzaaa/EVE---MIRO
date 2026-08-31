"""Shared fetch helpers: fixture fallback, no invented live data."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from eve_miro.config import FIXTURES_DIR


def fixtures_enabled() -> bool:
    return os.environ.get("FIXTURES", "1") not in {"0", "false", "False"}


def load_fixture(name: str) -> Any:
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"fixture missing: {path}")
    return json.loads(path.read_text())


async def http_get_json(url: str, *, timeout: float = 20.0) -> Any:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
