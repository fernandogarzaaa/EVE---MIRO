"""WorldState → MiroFish-shaped structured seed.

Do not dump the whole WorldState into one prompt blob as the only
representation. Structured fields are required. A compact seed_document
is extra context for a future MiroFish HTTP call, labeled SIMULATED
(not an observation).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from pydantic import BaseModel, Field

from eve_miro.core.simulation.population import Persona
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.state import WorldState
from eve_miro.core.world.temporal import iso


class MiroEnvironment(BaseModel):
    physical_conditions: dict[str, Any] = Field(default_factory=dict)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    infrastructure: dict[str, Any] = Field(default_factory=dict)
    active_events: list[dict[str, Any]] = Field(default_factory=list)
    information_environment: dict[str, Any] = Field(default_factory=dict)


class SimulationContext(BaseModel):
    information_cutoff: datetime
    world_id: str
    timestamp: datetime
    input_provenance: list[dict[str, Any]] = Field(default_factory=list)


class MiroWorldSeed(BaseModel):
    environment: MiroEnvironment
    population_personas: list[dict[str, Any]] = Field(default_factory=list)
    context: SimulationContext
    seed_document: str = ""
    seed_document_kind: str = ProvenanceKind.SIMULATED.value
    seed_document_note: str = (
        "SIMULATED context for a future MiroFish HTTP call; not an observation."
    )

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "physical_conditions": self.environment.physical_conditions,
            "locations": self.environment.locations,
            "infrastructure": self.environment.infrastructure,
            "active_events": self.environment.active_events,
            "information_environment": self.environment.information_environment,
            "information_cutoff": iso(self.context.information_cutoff),
            "timestamp": iso(self.context.timestamp),
            "world_id": self.context.world_id,
            "input_provenance": self.context.input_provenance,
            "population_n": len(self.population_personas),
            "seed_document": self.seed_document,
            "seed_document_kind": self.seed_document_kind,
            "seed_document_note": self.seed_document_note,
        }


def _compact_seed_document(world: WorldState, n_personas: int, n_events: int) -> str:
    weather = (world.environment.weather or {}).get("latest") or {}
    wind = weather.get("wind_speed_10m")
    kind = weather.get("kind")
    return (
        "SIMULATED context (not an observation). "
        f"World {world.world_id} at {iso(world.timestamp)}; "
        f"information_cutoff={iso(world.information_cutoff)}. "
        f"Region {world.geography.region}. "
        f"Latest folded weather wind_speed_10m={wind} kind={kind}. "
        f"Folded events={n_events}. "
        f"Synthetic statistical personas n={n_personas} (not real people)."
    )


class MiroWorldAdapter:
    """Structured WorldState → MiroEnvironment + population + SimulationContext."""

    def adapt(
        self,
        world: WorldState,
        personas: Sequence[Persona] | None = None,
        events: Sequence[WorldEvent] | None = None,
    ) -> MiroWorldSeed:
        personas = list(personas or [])
        events = list(events or [])
        weather = dict(world.environment.weather or {})
        physical = {
            "weather": {
                "latest": weather.get("latest") or {},
                "series_n": weather.get("series_n") or len(weather.get("series") or []),
                "kind": weather.get("kind"),
            },
            "seismic": dict(world.environment.seismic or {}),
            "hazards_n": len(world.environment.hazards or []),
        }
        locations = [
            {
                "region": world.geography.region,
                "centroid": list(world.geography.centroid),
                "bbox": list(world.geography.bbox),
            }
        ]
        if personas:
            locations.append(
                {
                    "kind": "population_sample",
                    "n": len(personas),
                    "lat": personas[0].lat,
                    "lon": personas[0].lon,
                    "notes": "Synthetic statistical personas. Not real people.",
                }
            )
        active_events: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        folded = set(world.events)
        for event in events:
            if folded and event.id not in folded:
                continue
            kind = event.kind.value
            provenance.append(
                {
                    "event_id": event.id,
                    "kind": kind,
                    "provider": event.source.provider,
                    "dataset": event.source.dataset,
                    "version": event.source.version,
                    "event_type": event.event_type,
                }
            )
            if len(active_events) < 32:
                active_events.append(
                    {
                        "id": event.id,
                        "event_type": event.event_type,
                        "kind": kind,
                        "provider": event.source.provider,
                    }
                )
        if not provenance and world.quality.get("kinds"):
            for k in world.quality.get("kinds") or []:
                provenance.append({"kind": k, "source": "world.quality"})

        information_environment = {
            "alerts": list(world.information.alerts or []),
            "news_mentions": world.information.news_mentions,
            "note": "Agents perceive a subset; see AgentObservation. Not omniscient.",
        }
        env = MiroEnvironment(
            physical_conditions=physical,
            locations=locations,
            infrastructure=dict(world.infrastructure.status or {}),
            active_events=active_events,
            information_environment=information_environment,
        )
        ctx = SimulationContext(
            information_cutoff=world.information_cutoff,
            world_id=world.world_id,
            timestamp=world.timestamp,
            input_provenance=provenance,
        )
        persona_rows = [
            {
                "agent_id": p.agent_id,
                "age_band": p.age_band,
                "lat": p.lat,
                "lon": p.lon,
                "role": p.role,
                "notes": p.notes,
            }
            for p in personas[:80]
        ]
        return MiroWorldSeed(
            environment=env,
            population_personas=persona_rows,
            context=ctx,
            seed_document=_compact_seed_document(world, len(personas), len(provenance)),
        )
