"""Clock helpers. All timestamps are timezone-aware UTC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Union

DateLike = Union[datetime, str]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: DateLike) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        # Open-Meteo hourly stamps are naive ISO-8601 in the requested timezone (UTC here).
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_offset(spec: str, origin: datetime) -> datetime:
    """Parse scenario offsets like '+6h' or ISO timestamps."""
    spec = spec.strip()
    if spec.startswith("+"):
        amount = spec[1:]
        if amount.endswith("h"):
            return origin + timedelta(hours=float(amount[:-1]))
        if amount.endswith("m"):
            return origin + timedelta(minutes=float(amount[:-1]))
        if amount.endswith("d"):
            return origin + timedelta(days=float(amount[:-1]))
        raise ValueError(f"unsupported offset: {spec}")
    return as_utc(spec)


def iso(dt: datetime) -> str:
    return as_utc(dt).isoformat().replace("+00:00", "Z")
