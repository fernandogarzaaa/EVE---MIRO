"""Recorded OASIS/MiroFish payload maps to traces, weather series, and MAE."""

from __future__ import annotations

import pytest

from eve_miro.core.orchestration.closed_loop import split_at_cutoff
from eve_miro.core.orchestration.experiment import load_experiment
from eve_miro.core.orchestration.reality_alignment import RealityAligner
from eve_miro.core.orchestration.world_to_miro import MiroWorldAdapter
from eve_miro.core.simulation.engine import Simulation
from eve_miro.core.simulation.mirofish_client import map_mirofish_result
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.projector import project_world_state
from eve_miro.providers.common import load_fixture
from eve_miro.providers.weather import OpenMeteoProvider


def _t0_t1():
    spec = load_experiment("typhoon_manila_closed_loop")
    events = OpenMeteoProvider(mode="archive").normalize(load_fixture("openmeteo_manila_archive.json"))
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    return spec, t0, t1


def _simulation_with_weather(spec, t0, hours: int = 6) -> Simulation:
    origin = spec.cutoff
    world = project_world_state(
        "w_oasis_map",
        t0,
        at=origin,
        information_cutoff=origin,
        reject_leaks=True,
        synthetic_population=8,
    )
    seed = MiroWorldAdapter().adapt(world, events=t0)
    return Simulation(
        id="sim_oasis_map",
        world_id="w_oasis_map",
        scenario_name="typhoon_manila_001:baseline",
        information_cutoff=origin,
        origin=origin,
        hours=hours,
        seed=1,
        population_n=8,
        world_snapshot=seed.to_snapshot(),
        scenario_type="typhoon",
    )


def test_recorded_oasis_slice_maps_create_post_and_weather():
    spec, t0, t1 = _t0_t1()
    assert t0 and t1
    sim = _simulation_with_weather(spec, t0, hours=6)
    payload = load_fixture("mirofish_oasis_twitter_slice.json")
    result = map_mirofish_result(sim, payload)
    assert result.summary["actions_n"] > 0
    assert result.traces
    actions = [row["action"] for row in result.traces]
    assert any(a == "CREATE_POST" for a in actions)
    assert "stay" not in {a for a in actions if "CREATE_POST" in a}
    assert "wind_speed_10m" in result.predicted_series
    assert result.predicted_series["wind_speed_10m"]
    assert "congestion" in result.predicted_series
    assert result.summary["peak_wind"] is not None
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED


def test_oasis_slice_alignment_mae_not_none():
    spec, t0, t1 = _t0_t1()
    sim = _simulation_with_weather(spec, t0, hours=6)
    payload = load_fixture("mirofish_oasis_twitter_slice.json")
    mapped = map_mirofish_result(sim, payload)
    alignments = RealityAligner().align(
        predicted_series=mapped.predicted_series,
        predicted_times=mapped.predicted_times,
        t1_events=t1,
        input_provenance_kinds=["observed"],
        metrics=["mae", "brier", "calibration"],
    )
    wind = [a for a in alignments if a.metric_name == "wind_speed_10m"]
    assert wind
    assert wind[0].mae is not None
    cong = [a for a in alignments if a.metric_name == "congestion"]
    assert cong
    assert cong[0].predicted


@pytest.mark.asyncio
async def test_closed_loop_with_mapped_oasis_slice_mae(monkeypatch):
    from eve_miro.core.orchestration.closed_loop import ClosedLoop
    from eve_miro.storage.event_store import InMemoryEventStore

    spec, t0, t1 = _t0_t1()
    payload = load_fixture("mirofish_oasis_twitter_slice.json")

    async def fake_run(self, simulation, until):
        mapped = map_mirofish_result(simulation, payload)
        mapped.summary["engine"] = "mirofish"
        return mapped

    monkeypatch.setattr(
        "eve_miro.core.simulation.engine.StubSimulationEngine.run",
        fake_run,
    )
    result = await ClosedLoop().run(
        spec,
        InMemoryEventStore(),
        t0,
        t1,
        agents=8,
        seeds=[1],
        horizon_hours=6,
        world_id="w_oasis_loop",
    )
    wind_align = [a for a in result.alignments if a.metric_name == "wind_speed_10m"]
    assert wind_align
    assert any(a.mae is not None for a in wind_align)
    assert any(r.summary.get("actions_n", 0) > 0 for r in result.seed_runs)
