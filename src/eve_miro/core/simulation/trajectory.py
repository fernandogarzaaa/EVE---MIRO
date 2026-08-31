"""Agent trajectories produced from simulation traces/steps.

EVE never imports MiroFish internals; `miro_to_eve` turns these into the
ExperienceEngine `Trajectory` contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field

from eve_miro.core.simulation.observation import AgentObservation
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.temporal import as_utc, iso


class TrajectoryStep(BaseModel):
    t: datetime
    hour: int
    action: str
    outcome: str | None = None
    wind_speed: float | None = None
    congestion: float | None = None
    warning_active: bool = False
    warning_received: bool = False
    observation: AgentObservation | None = None
    provenance_kind: ProvenanceKind = ProvenanceKind.SIMULATED


class AgentTrajectory(BaseModel):
    agent_id: str
    simulation_id: str
    seed: int = 0
    scenario_id: str = ""
    steps: list[TrajectoryStep] = Field(default_factory=list)
    provenance_kind: ProvenanceKind = ProvenanceKind.SIMULATED


def agent_trajectories_from_result(
    result: Any,
    *,
    observations: dict[str, AgentObservation] | None = None,
    scenario_id: str = "",
    seed: int | None = None,
) -> list[AgentTrajectory]:
    """Convert SimulationResult traces/steps into per-agent trajectories."""
    sim = result.simulation
    seed_v = int(seed if seed is not None else getattr(sim, "seed", 0) or 0)
    obs = observations or {}
    by_agent: dict[str, list[TrajectoryStep]] = {}

    traces: Iterable[dict[str, Any]] = result.traces or []
    if traces:
        for row in traces:
            agent_id = str(row.get("agent_id") or "")
            if not agent_id:
                continue
            t_raw = row.get("t")
            try:
                t = as_utc(t_raw) if t_raw else sim.origin
            except Exception:
                t = sim.origin
            step = TrajectoryStep(
                t=t,
                hour=int(row.get("hour") or 0),
                action=str(row.get("action") or "stay"),
                outcome=row.get("outcome"),
                wind_speed=_f(row.get("wind_speed")),
                congestion=_f(row.get("congestion")),
                warning_active=bool(row.get("warning_active")),
                warning_received=bool(row.get("warning_received")),
                observation=obs.get(agent_id),
                provenance_kind=ProvenanceKind.SIMULATED,
            )
            by_agent.setdefault(agent_id, []).append(step)
    else:
        for st in getattr(sim, "steps", []) or []:
            for a in getattr(st, "actions", []) or []:
                agent_id = a.agent_id
                step = TrajectoryStep(
                    t=a.t,
                    hour=a.hour,
                    action=a.action,
                    outcome=a.outcome,
                    wind_speed=a.wind_speed,
                    congestion=a.congestion,
                    warning_active=a.warning_active,
                    warning_received=a.warning_received,
                    observation=obs.get(agent_id),
                    provenance_kind=ProvenanceKind.SIMULATED,
                )
                by_agent.setdefault(agent_id, []).append(step)

    out: list[AgentTrajectory] = []
    for agent_id, steps in by_agent.items():
        steps.sort(key=lambda s: (s.hour, iso(s.t)))
        out.append(
            AgentTrajectory(
                agent_id=agent_id,
                simulation_id=sim.id,
                seed=seed_v,
                scenario_id=scenario_id,
                steps=steps,
            )
        )
    out.sort(key=lambda t: t.agent_id)
    return out


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
