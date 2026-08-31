"""Historical replay: refuse any event after information_cutoff. No future leakage."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from eve_miro.core.world.events import WorldEvent
from eve_miro.core.world.projector import project_world_state, select_events
from eve_miro.core.world.state import WorldState
from eve_miro.core.world.temporal import as_utc
from eve_miro.errors import FutureLeakageError, ReplayError


def assert_no_future_events(events: Iterable[WorldEvent], information_cutoff: datetime) -> None:
    cutoff = as_utc(information_cutoff)
    leaked = [e for e in events if as_utc(e.temporal.effective_time) > cutoff]
    if leaked:
        raise ReplayError(
            f"historical replay refuses {len(leaked)} event(s) after information_cutoff "
            f"{cutoff.isoformat()} (e.g. {leaked[0].id})"
        )


def replay_world(
    world_id: str,
    events: Iterable[WorldEvent],
    *,
    at: datetime,
    information_cutoff: datetime,
) -> WorldState:
    events = list(events)
    try:
        assert_no_future_events(events, information_cutoff)
    except ReplayError as exc:
        raise FutureLeakageError(str(exc)) from exc
    selected = select_events(events, at=at, information_cutoff=information_cutoff, reject_leaks=True)
    return project_world_state(
        world_id,
        selected,
        at=at,
        information_cutoff=information_cutoff,
        reject_leaks=True,
    )
