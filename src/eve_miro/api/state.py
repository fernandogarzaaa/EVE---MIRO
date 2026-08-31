"""In-process registries. Postgres is optional; tests use this + InMemoryEventStore."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from eve_miro.core.evaluation.reality_check import Evaluation
from eve_miro.core.experience.graph import ExperienceGraph
from eve_miro.core.experience.validation import ValidatedExperience
from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.reality.trust_profile import TrustProfile
from eve_miro.core.simulation.engine import Simulation, SimulationResult
from eve_miro.core.world.temporal import utcnow
from eve_miro.storage.event_store import EventStore, InMemoryEventStore, get_event_store


@dataclass
class WorldRecord:
    id: str
    created_at: datetime
    region: str = "philippines"
    information_cutoff: datetime | None = None
    label: str = ""


@dataclass
class AppState:
    store: EventStore = field(default_factory=get_event_store)
    worlds: dict[str, WorldRecord] = field(default_factory=dict)
    simulations: dict[str, Simulation] = field(default_factory=dict)
    results: dict[str, SimulationResult] = field(default_factory=dict)
    experiences: dict[str, ValidatedExperience] = field(default_factory=dict)
    evaluations: dict[str, Evaluation] = field(default_factory=dict)
    scenarios: dict[str, dict[str, Any]] = field(default_factory=dict)
    ledger: RealityLedger = field(default_factory=RealityLedger)
    trust_profile: TrustProfile | None = None
    experience_graph: ExperienceGraph = field(default_factory=ExperienceGraph)
    experiments: dict[str, Any] = field(default_factory=dict)


STATE = AppState()


def reset_state() -> AppState:
    global STATE
    from eve_miro.storage.event_store import reset_memory_store

    STATE = AppState(store=reset_memory_store())
    return STATE
