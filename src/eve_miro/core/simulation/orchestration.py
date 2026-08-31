"""Run a scenario: cutoff-bounded world → stub sim → traces → experiences."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from eve_miro.config import TRACES_DIR
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.simulation.engine import StubSimulationEngine
from eve_miro.core.simulation.replay import replay_world
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import WorldEvent
from eve_miro.core.world.state import Population
from eve_miro.storage.analytics import write_trace_parquet


async def run_scenario(
    world_id: str,
    events: list[WorldEvent],
    scenario: Scenario,
    *,
    traces_dir: Path | None = None,
):
    world = replay_world(
        world_id,
        events,
        at=scenario.origin,
        information_cutoff=scenario.cutoff,
    )
    engine = StubSimulationEngine(scenario)
    sim = await engine.initialize(world, Population(synthetic_n=scenario.population))
    until = scenario.origin + timedelta(hours=scenario.simulated_hours)
    result = await engine.run(sim, until)
    path = (traces_dir or TRACES_DIR) / f"{sim.id}.parquet"
    if result.traces:
        write_trace_parquet(result.traces, path)
        result.summary["trace_path"] = str(path)
    exp_engine = StubExperienceEngine()
    from eve_miro.core.experience.candidates import Trajectory

    traj = Trajectory(simulation_id=sim.id, actions=result.traces, predicted_series=result.predicted_series)
    candidates = await exp_engine.observe(traj)
    validated = [await exp_engine.validate(c) for c in candidates]
    selected = await exp_engine.select(validated, budget=int(scenario.conditions.get("memory_budget", 4096)))
    result.summary["experiences"] = [v.model_dump(mode="json") for v in selected]
    return result, selected
