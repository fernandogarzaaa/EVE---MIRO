"""Append-only event store. History is never mutated. Default is in-memory for tests."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Protocol, runtime_checkable

from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.quality import run_quality
from eve_miro.core.world.temporal import as_utc


@runtime_checkable
class EventStore(Protocol):
    def append(
        self,
        world_id: str,
        event: WorldEvent,
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
    ) -> None: ...

    def append_many(
        self,
        world_id: str,
        events: list[WorldEvent],
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
        information_cutoff: datetime | None = None,
    ) -> list[WorldEvent]: ...

    def list(
        self,
        world_id: str,
        *,
        up_to: datetime | None = None,
        kinds: list[ProvenanceKind] | None = None,
    ) -> list[WorldEvent]: ...


class InMemoryEventStore:
    """Process-local append-only log. Default when Postgres is not up."""

    def __init__(self) -> None:
        self._log: dict[str, list[WorldEvent]] = {}
        self._ids: set[str] = set()

    def append(
        self,
        world_id: str,
        event: WorldEvent,
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
    ) -> None:
        self.append_many(world_id, [event], channel=channel)

    def append_many(
        self,
        world_id: str,
        events: list[WorldEvent],
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
        information_cutoff: datetime | None = None,
    ) -> list[WorldEvent]:
        report = run_quality(events, channel=channel, information_cutoff=information_cutoff)
        accepted: list[WorldEvent] = []
        for event in report.accepted:
            key = f"{world_id}:{event.id}"
            if key in self._ids:
                continue
            # freeze into the log; never update in place
            self._log.setdefault(world_id, []).append(event)
            self._ids.add(key)
            accepted.append(event)
        return accepted

    def list(
        self,
        world_id: str,
        *,
        up_to: datetime | None = None,
        kinds: list[ProvenanceKind] | None = None,
    ) -> list[WorldEvent]:
        rows = list(self._log.get(world_id, []))
        if up_to is not None:
            cut = as_utc(up_to)
            rows = [e for e in rows if e.temporal.effective_time <= cut]
        if kinds is not None:
            allowed = set(kinds)
            rows = [e for e in rows if e.provenance.kind in allowed]
        return list(rows)


_STORE: InMemoryEventStore | None = None


def get_event_store() -> EventStore:
    global _STORE
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        from eve_miro.storage.postgres import PostgresEventStore

        return PostgresEventStore(url)
    if _STORE is None:
        _STORE = InMemoryEventStore()
    return _STORE


def reset_memory_store() -> InMemoryEventStore:
    global _STORE
    _STORE = InMemoryEventStore()
    return _STORE
