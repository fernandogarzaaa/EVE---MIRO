"""Trajectories → ExperienceEngine.observe / validate.

EVE receives Trajectory only. This module does not import MiroFish internals.
"""

from __future__ import annotations

from typing import Any, Sequence

from eve_miro.core.experience.candidates import Trajectory
from eve_miro.core.experience.engine import ExperienceEngine
from eve_miro.core.experience.validation import ValidatedExperience
from eve_miro.core.simulation.trajectory import AgentTrajectory
from eve_miro.core.world.temporal import iso


def to_engine_trajectory(
    trajectories: Sequence[AgentTrajectory],
    *,
    simulation_id: str | None = None,
    predicted_series: dict[str, list[float]] | None = None,
    observed_series: dict[str, list[float]] | None = None,
    world_state_timestamp: str | None = None,
    event_ids: list[str] | None = None,
    source_providers: list[str] | None = None,
    episode_id: str = "episode_81",
) -> Trajectory:
    """Adapter: AgentTrajectory list → ExperienceEngine Trajectory contract."""
    actions: list[dict[str, Any]] = []
    sim_id = simulation_id or (trajectories[0].simulation_id if trajectories else "sim")
    for traj in trajectories:
        for step in traj.steps:
            actions.append(
                {
                    "simulation_id": traj.simulation_id,
                    "agent_id": traj.agent_id,
                    "hour": step.hour,
                    "t": iso(step.t),
                    "action": step.action,
                    "outcome": step.outcome,
                    "wind_speed": step.wind_speed,
                    "congestion": step.congestion,
                    "warning_active": step.warning_active,
                    "warning_received": step.warning_received,
                    "provenance_kind": (
                        step.provenance_kind.value
                        if hasattr(step.provenance_kind, "value")
                        else str(step.provenance_kind)
                    ),
                }
            )
    return Trajectory(
        simulation_id=sim_id,
        actions=actions,
        predicted_series=dict(predicted_series or {}),
        observed_series=dict(observed_series or {}),
        episode_id=episode_id,
        world_state_timestamp=world_state_timestamp,
        event_ids=list(event_ids or []),
        source_providers=list(source_providers or []),
    )


async def observe_and_validate(
    engine: ExperienceEngine,
    trajectories: Sequence[AgentTrajectory],
    *,
    predicted_series: dict[str, list[float]] | None = None,
    observed_series: dict[str, list[float]] | None = None,
    world_state_timestamp: str | None = None,
    event_ids: list[str] | None = None,
    source_providers: list[str] | None = None,
    simulation_id: str | None = None,
    validate: bool = True,
    episode_id: str = "episode_81",
) -> list[ValidatedExperience]:
    traj = to_engine_trajectory(
        trajectories,
        simulation_id=simulation_id,
        predicted_series=predicted_series,
        observed_series=observed_series,
        world_state_timestamp=world_state_timestamp,
        event_ids=event_ids,
        source_providers=source_providers,
        episode_id=episode_id,
    )
    candidates = await engine.observe(traj)
    if not validate:
        # still wrap via validate so callers get ValidatedExperience
        return [await engine.validate(c) for c in candidates]
    return [await engine.validate(c) for c in candidates]
