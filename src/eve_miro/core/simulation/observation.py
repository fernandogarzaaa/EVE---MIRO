"""Agent perception filter. World events are NOT every agent's memory.

An agent only sees events they are exposed to (news if coverage/random
exposure, weather at their lat/lon, disaster alerts if in region).
`accessible_information` is always a subset. Uncertainty > 0 when anything
is withheld. No omniscience.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, Field

from eve_miro.core.evaluation.metrics import geographic_distance_km
from eve_miro.core.simulation.population import Persona
from eve_miro.core.world.events import WorldEvent
from eve_miro.core.world.state import WorldState
from eve_miro.core.world.temporal import as_utc, utcnow

WEATHER_RADIUS_KM = 80.0
ALERT_RADIUS_KM = 250.0
NEWS_EXPOSURE_RATE = 0.35
NEWS_TYPES = {"news.article", "news", "news.mention"}
NEWS_PROVIDERS = {"gdelt"}


class AgentObservation(BaseModel):
    """What one synthetic agent actually perceived at time t. Not the full WorldState."""

    agent_id: str
    t: datetime
    observed_events: list[str] = Field(default_factory=list)
    accessible_information: dict[str, Any] = Field(default_factory=dict)
    withheld_event_ids: list[str] = Field(default_factory=list)
    uncertainty: float = 0.0
    lat: float
    lon: float
    local_weather: dict[str, Any] | None = None
    notes: str = "Perception is a subset of WorldState. Agents are not omniscient."


def _unit_hash(agent_id: str, event_id: str) -> float:
    digest = hashlib.sha256(f"{agent_id}|{event_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def _is_news(event: WorldEvent) -> bool:
    et = (event.event_type or "").lower()
    provider = (event.source.provider or "").lower()
    return et in NEWS_TYPES or et.startswith("news") or provider in NEWS_PROVIDERS


def _is_weather(event: WorldEvent) -> bool:
    return (event.event_type or "").startswith("weather")


def _is_alert(event: WorldEvent) -> bool:
    et = event.event_type or ""
    return (
        et.endswith("alert")
        or et.startswith("alert")
        or et.startswith("disaster")
        or et.startswith("earthquake")
        or et.startswith("hazard")
        or et.startswith("gdacs")
    )


def agent_exposed_to(agent: Persona, event: WorldEvent) -> bool:
    """True iff this agent would perceive the event. News is never universal."""
    if _is_news(event):
        return _unit_hash(agent.agent_id, event.id) < NEWS_EXPOSURE_RATE
    if _is_weather(event):
        if event.location is None:
            return True
        dist = geographic_distance_km(agent.lat, agent.lon, event.location.lat, event.location.lon)
        return dist <= WEATHER_RADIUS_KM
    if _is_alert(event):
        if event.location is None:
            return True
        dist = geographic_distance_km(agent.lat, agent.lon, event.location.lat, event.location.lon)
        return dist <= ALERT_RADIUS_KM
    # Unknown types are not automatically in every agent's memory.
    return False


def _subset_payload(event: WorldEvent) -> dict[str, Any]:
    keys = ("title", "wind_speed_10m", "precipitation", "temperature_2m", "mag", "place", "type")
    payload = {k: event.payload.get(k) for k in keys if k in event.payload}
    return {
        "id": event.id,
        "event_type": event.event_type,
        "kind": event.kind.value,
        "provider": event.source.provider,
        "payload": payload,
    }


def perceive(
    agent: Persona,
    world: WorldState,
    events: Sequence[WorldEvent],
    *,
    t: datetime | None = None,
) -> AgentObservation:
    """Filter WorldState events into this agent's observation. Never copies the full log."""
    when = as_utc(t) if t is not None else world.timestamp
    folded = set(world.events) if world.events else {e.id for e in events}
    candidates = [e for e in events if e.id in folded]
    observed: list[WorldEvent] = []
    withheld: list[str] = []
    for event in candidates:
        if agent_exposed_to(agent, event):
            observed.append(event)
        else:
            withheld.append(event.id)

    local_weather: dict[str, Any] | None = None
    for event in observed:
        if _is_weather(event) and event.payload:
            local_weather = {
                "wind_speed_10m": event.payload.get("wind_speed_10m"),
                "precipitation": event.payload.get("precipitation"),
                "temperature_2m": event.payload.get("temperature_2m"),
                "kind": event.kind.value,
            }

    n = len(candidates)
    uncertainty = (len(withheld) / n) if n else 0.0
    if withheld and uncertainty <= 0.0:
        uncertainty = 0.01

    accessible = {
        "event_ids": [e.id for e in observed],
        "event_types": sorted({e.event_type for e in observed}),
        "weather": local_weather or {},
        "alerts": [_subset_payload(e) for e in observed if _is_alert(e)],
        "news": [_subset_payload(e) for e in observed if _is_news(e)],
        "world_id": world.world_id,
        "information_cutoff": world.information_cutoff.isoformat(),
    }
    return AgentObservation(
        agent_id=agent.agent_id,
        t=when,
        observed_events=[e.id for e in observed],
        accessible_information=accessible,
        withheld_event_ids=withheld,
        uncertainty=uncertainty,
        lat=agent.lat,
        lon=agent.lon,
        local_weather=local_weather,
    )


def perceive_population(
    personas: Iterable[Persona],
    world: WorldState,
    events: Sequence[WorldEvent],
    *,
    t: datetime | None = None,
) -> dict[str, AgentObservation]:
    return {p.agent_id: perceive(p, world, events, t=t) for p in personas}


def utcnow_obs() -> datetime:
    return utcnow()
