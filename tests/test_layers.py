"""Three experience layers and learning artifacts consumed by the sim engine."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from eve_miro.core.experience.candidates import Trajectory
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.experience.layers import (
    LAYER_NAMES,
    AgentExperience,
    PopulationExperience,
    SimulatorExperience,
    as_layer,
)
from eve_miro.core.simulation.engine import StubSimulationEngine
from eve_miro.core.simulation.scenarios import Intervention, Scenario
from eve_miro.core.world.state import Population, WorldState
from eve_miro.core.world.events import ProvenanceKind


def _world(n: int = 80) -> tuple[WorldState, Population]:
    t = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    return WorldState(world_id="w", timestamp=t, information_cutoff=t), Population(synthetic_n=n)


def _late_warning_scenario() -> Scenario:
    return Scenario(
        name="late_warn",
        initial_world={"timestamp": "2026-08-31T10:00:00Z"},
        duration={"simulated_hours": 48},
        agents={"population": 80},
        interventions=[Intervention(type="evacuation_warning", timestamp="+40h", coverage=0.8)],
        random_seed=48291,
        information_cutoff="2026-08-31T10:00:00Z",
    )


@pytest.mark.asyncio
async def test_observe_emits_all_three_layers():
    engine = StubExperienceEngine()
    traj = Trajectory(
        simulation_id="sim_x",
        actions=[
            {"action": "stuck", "agent_id": "persona_0001", "hour": 4, "congestion": 0.6, "warning_active": True}
        ],
        predicted_series={"wind_speed_10m": [10.0, 12.0]},
        observed_series={"wind_speed_10m": [11.0, 12.0]},
        episode_id="episode_81",
        event_ids=["ev1"],
        source_providers=["openmeteo"],
        world_state_timestamp="2026-08-31T10:00:00+00:00",
    )
    cands = await engine.observe(traj)
    assert {c.layer for c in cands} >= set(LAYER_NAMES)
    models = [as_layer(c) for c in cands]
    assert any(isinstance(m, AgentExperience) for m in models)
    assert any(isinstance(m, PopulationExperience) for m in models)
    assert any(isinstance(m, SimulatorExperience) for m in models)
    sim_layer = next(m for m in models if isinstance(m, SimulatorExperience))
    assert "wind_speed_10m" in sim_layer.predicted
    assert sim_layer.observed.get("wind_speed_10m") == [11.0, 12.0]


@pytest.mark.asyncio
async def test_learning_artifact_changes_subsequent_seeded_run():
    world, pop = _world()
    sc = _late_warning_scenario()
    baseline = StubSimulationEngine(sc)
    sim_a = await baseline.initialize(world, pop)
    until = sim_a.origin + timedelta(hours=sc.simulated_hours)
    res_a = await baseline.run(sim_a, until)

    exp = StubExperienceEngine()
    traj = Trajectory(simulation_id=sim_a.id, actions=res_a.traces, predicted_series=res_a.predicted_series)
    cands = await exp.observe(traj)
    validated = [await exp.validate(c) for c in cands]
    artifacts = [v.artifact for v in validated if v.artifact]
    assert artifacts
    assert artifacts[0]["confidence"] > 0.8
    assert artifacts[0]["source"]
    assert artifacts[0]["provenance_kind"] == ProvenanceKind.SIMULATED.value

    learned = StubSimulationEngine(sc, artifacts=artifacts)
    sim_b = await learned.initialize(world, pop)
    res_b = await learned.run(sim_b, until)

    assert sim_a.seed == sim_b.seed
    assert res_a.summary["cascade_reduced"] is False
    assert res_b.summary["cascade_reduced"] is True
    assert res_b.summary["peak_congestion"] < res_a.summary["peak_congestion"]
    assert res_b.summary["stuck"] <= res_a.summary["stuck"]
