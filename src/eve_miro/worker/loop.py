"""Ingest/project loop invoked by the API in v1 (no separate worker process required)."""

from __future__ import annotations

from datetime import datetime

from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS, Region
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.projector import project_world_state
from eve_miro.core.world.temporal import as_utc
from eve_miro.providers.protocol import TimeWindow
from eve_miro.providers.registry import get_provider
from eve_miro.storage.event_store import EventStore
from eve_miro.streaming.bus import BUS
from eve_miro.streaming.topics import TOPICS


async def ingest_from_providers(
    store: EventStore,
    world_id: str,
    names: list[str],
    window: TimeWindow,
    *,
    region: Region | None = None,
    channel: ProvenanceKind = ProvenanceKind.OBSERVED,
    information_cutoff: datetime | None = None,
) -> list[WorldEvent]:
    region = region or PHILIPPINES
    accepted: list[WorldEvent] = []
    for name in names:
        provider = get_provider(name)
        kind = provider.provenance().kind
        # forecast provider must not ride the observed channel
        use_channel = kind if kind != ProvenanceKind.OBSERVED else channel
        events = await provider.fetch(window, region)
        if use_channel == ProvenanceKind.OBSERVED:
            stored = store.append_many(
                world_id, events, channel=ProvenanceKind.OBSERVED, information_cutoff=information_cutoff
            )
        else:
            stored = store.append_many(
                world_id, events, channel=use_channel, information_cutoff=information_cutoff
            )
        for e in stored:
            BUS.publish(TOPICS["world.events"], e.model_dump(mode="json"))
        accepted.extend(stored)
    return accepted


def provider_cadence() -> dict[str, float]:
    return {k: v.total_seconds() for k, v in PROVIDER_INTERVALS.items()}
