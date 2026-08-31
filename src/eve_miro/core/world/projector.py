"""Event-sourced WorldState projector. Never mutates history; always rebuilds from the log."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from eve_miro.config import PHILIPPINES
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.provenance import ProvenanceEdge, ProvenanceGraph, ProvenanceNode
from eve_miro.core.world.state import (
    Economy,
    Environment,
    Geography,
    InformationLayer,
    Infrastructure,
    Mobility,
    Population,
    WorldState,
)
from eve_miro.core.world.temporal import as_utc
from eve_miro.errors import FutureLeakageError


def _event_time(event: WorldEvent) -> datetime:
    return as_utc(event.temporal.effective_time)


def select_events(
    events: Iterable[WorldEvent],
    *,
    at: datetime,
    information_cutoff: datetime,
    reject_leaks: bool = False,
) -> list[WorldEvent]:
    at = as_utc(at)
    cutoff = as_utc(information_cutoff)
    if at > cutoff:
        # Reconstructing a later wall-clock is allowed only with data known at cutoff.
        at = cutoff
    selected: list[WorldEvent] = []
    leaked: list[WorldEvent] = []
    for event in events:
        t = _event_time(event)
        extra = []
        if event.information_cutoff is not None:
            extra.append(as_utc(event.information_cutoff))
        too_late = t > cutoff or any(x > cutoff for x in extra)
        if too_late:
            leaked.append(event)
            continue
        if t <= at:
            selected.append(event)
    if reject_leaks and leaked:
        ids = ", ".join(e.id for e in leaked[:8])
        raise FutureLeakageError(
            f"{len(leaked)} event(s) after information_cutoff {cutoff.isoformat()} refused: {ids}"
        )
    selected.sort(key=_event_time)
    return selected


def project_world_state(
    world_id: str,
    events: Iterable[WorldEvent],
    *,
    at: datetime,
    information_cutoff: datetime,
    reject_leaks: bool = False,
    synthetic_population: int = 0,
) -> WorldState:
    chosen = select_events(events, at=at, information_cutoff=information_cutoff, reject_leaks=reject_leaks)
    weather: dict = {}
    weather_series: list[dict] = []
    seismic: dict = {}
    quakes: list[dict] = []
    aircraft = 0
    vessels = 0
    samples: list[dict] = []
    alerts: list[dict] = []
    graph = ProvenanceGraph()

    for event in chosen:
        src_id = f"source:{event.source.provider}:{event.source.dataset}"
        graph.add_node(
            ProvenanceNode(
                id=src_id,
                type="source",
                label=f"{event.source.provider}/{event.source.dataset}",
                provenance_kind=event.provenance.kind,
            )
        )
        graph.add_node(
            ProvenanceNode(
                id=f"event:{event.id}",
                type="event",
                label=event.event_type,
                provenance_kind=event.provenance.kind,
            )
        )
        graph.add_edge(ProvenanceEdge(src=src_id, dst=f"event:{event.id}", rel="emitted"))

        if event.event_type.startswith("weather"):
            row = {
                "time": event.temporal.effective_time.isoformat(),
                "temperature_2m": event.payload.get("temperature_2m"),
                "precipitation": event.payload.get("precipitation"),
                "wind_speed_10m": event.payload.get("wind_speed_10m"),
                "wind_gusts_10m": event.payload.get("wind_gusts_10m"),
                "relative_humidity_2m": event.payload.get("relative_humidity_2m"),
                "kind": event.provenance.kind.value,
            }
            weather_series.append(row)
            weather = {
                "latest": row,
                "series_n": len(weather_series),
                "kind": event.provenance.kind.value,
            }
        elif event.event_type.startswith("earthquake"):
            quakes.append(
                {
                    "id": event.id,
                    "mag": event.payload.get("mag"),
                    "place": event.payload.get("place"),
                    "time": event.temporal.effective_time.isoformat(),
                    "conflicted": event.provenance.conflicted,
                }
            )
            seismic = {"count": len(quakes), "latest": quakes[-1]}
        elif event.event_type.startswith("aircraft"):
            aircraft += 1
            samples.append({"type": "aircraft", "id": event.id})
        elif event.event_type.startswith("vessel"):
            vessels += 1
            samples.append({"type": "vessel", "id": event.id})
        elif event.event_type.endswith("alert") or event.event_type.startswith("alert"):
            alerts.append({"id": event.id, "type": event.event_type, "payload": event.payload})

    state_id = f"state:{world_id}:{as_utc(at).isoformat()}"
    graph.add_node(
        ProvenanceNode(
            id=state_id,
            type="state",
            label=f"WorldState@ {as_utc(at).isoformat()}",
            provenance_kind=ProvenanceKind.DERIVED,
        )
    )
    for event in chosen:
        graph.add_edge(ProvenanceEdge(src=f"event:{event.id}", dst=state_id, rel="folded_into"))

    weather_out = dict(weather)
    if weather_series:
        weather_out["series"] = weather_series[-48:]

    return WorldState(
        world_id=world_id,
        timestamp=as_utc(at),
        information_cutoff=as_utc(information_cutoff),
        geography=Geography(
            region=PHILIPPINES.name,
            bbox=(PHILIPPINES.min_lat, PHILIPPINES.max_lat, PHILIPPINES.min_lon, PHILIPPINES.max_lon),
        ),
        environment=Environment(weather=weather_out, seismic=seismic, hazards=quakes),
        economy=Economy(),
        infrastructure=Infrastructure(),
        mobility=Mobility(aircraft_count=aircraft, vessel_count=vessels, samples=samples[:20]),
        information=InformationLayer(alerts=alerts),
        population=Population(synthetic_n=synthetic_population),
        events=[e.id for e in chosen],
        provenance_graph=graph,
        quality={"event_count": len(chosen), "kinds": sorted({e.kind.value for e in chosen})},
    )
