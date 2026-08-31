"""MiroFish / EVE adapters: in-tree default, stub runtime, optional local URL."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.engine import StubExperienceEngine, get_experience_engine
from eve_miro.core.experience.eve_adapter import EVEExperienceEngine
from eve_miro.core.simulation.engine import StubSimulationEngine, get_simulation_engine
from eve_miro.core.simulation.mirofish_adapter import MiroFishEngine
from eve_miro.core.simulation.scenarios import Scenario, load_scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState


def _world(n: int = 12) -> tuple[WorldState, Population]:
    t = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    return WorldState(world_id="w", timestamp=t, information_cutoff=t), Population(synthetic_n=n)


def _toy_scenario(*, stype: str = "typhoon") -> Scenario:
    return Scenario(
        name="toy",
        type=stype,
        initial_world={"timestamp": "2026-08-31T10:00:00Z"},
        duration={"simulated_hours": 3},
        agents={"population": 12},
        random_seed=48291,
        information_cutoff="2026-08-31T10:00:00Z",
    )


def test_factories_prefer_in_tree_adapters_which_stub(monkeypatch):
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_BIN", raising=False)
    monkeypatch.delenv("EVE_MIRO_ENGINES", raising=False)
    sim = get_simulation_engine()
    exp = get_experience_engine()
    assert isinstance(sim, MiroFishEngine)
    assert sim.using_remote is False
    assert isinstance(exp, EVEExperienceEngine)
    assert exp.using_remote is False


def test_factories_fallback_to_stub_when_in_tree_missing(monkeypatch):
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_BIN", raising=False)
    monkeypatch.setattr(
        "eve_miro.core.simulation.mirofish_adapter.in_tree_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "eve_miro.core.experience.eve_adapter.in_tree_available",
        lambda: False,
    )
    sim = get_simulation_engine()
    exp = get_experience_engine()
    assert isinstance(sim, StubSimulationEngine)
    assert not isinstance(sim, MiroFishEngine)
    assert isinstance(exp, StubExperienceEngine)
    assert not isinstance(exp, EVEExperienceEngine)


def test_factories_select_adapters_when_env_set(monkeypatch):
    monkeypatch.setenv("MIROFISH_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVE_URL", "http://127.0.0.1:9")
    sim = get_simulation_engine()
    exp = get_experience_engine()
    assert isinstance(sim, MiroFishEngine)
    assert isinstance(exp, EVEExperienceEngine)
    assert sim.using_remote is True
    assert exp.using_remote is True


@pytest.mark.asyncio
async def test_mirofish_delegates_to_stub_when_url_unset():
    world, pop = _world()
    sc = _toy_scenario()
    engine = MiroFishEngine(sc, url=None)
    assert engine.using_remote is False
    sim = await engine.initialize(world, pop)
    result = await engine.run(sim, sim.origin + timedelta(hours=sc.simulated_hours))
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED
    assert result.summary["provenance_kind"] == ProvenanceKind.SIMULATED.value
    assert "mirofish_unavailable" not in str(result.summary)


@pytest.mark.asyncio
async def test_mirofish_falls_back_when_remote_unavailable():
    world, pop = _world()
    sc = _toy_scenario()
    engine = MiroFishEngine(sc, url="http://127.0.0.1:1", timeout=0.2)
    sim = await engine.initialize(world, pop)
    result = await engine.run(sim, sim.origin + timedelta(hours=sc.simulated_hours))
    assert engine.last_notes == "mirofish_unavailable"
    assert result.summary.get("provenance_notes") == "mirofish_unavailable"
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED


@pytest.mark.asyncio
async def test_eve_falls_back_when_remote_unavailable():
    engine = EVEExperienceEngine(url="http://127.0.0.1:1", timeout=0.2)
    cand = ExperienceCandidate(
        id="exp_x",
        episode_id="episode_81",
        layer="agent",
        context={"peak_congestion": 0.6},
        observation={"stuck_n": 2},
        outcome="congestion_blocked",
    )
    val = await engine.validate(cand)
    assert engine.last_notes == "eve_unavailable"
    assert val.counterfactuals
    assert val.counterfactuals[0].label == "model-generated"
    assert val.counterfactuals[0].fact is False
    assert val.layer == "agent"


@pytest.mark.asyncio
async def test_market_scenario_runs_simulated_investors():
    sc = load_scenario(name="market_ph_001")
    assert sc.type == "market"
    assert "SIMULATED" in sc.disclaimer
    world, pop = _world(n=sc.population)
    # inject OBSERVED seed price into economy snapshot via a projected-like world
    world = world.model_copy(
        update={
            "economy": world.economy.model_copy(
                update={"indicators": {"market": {"latest": {"price": 64000.0, "symbol": "bitcoin", "kind": "observed"}}}}
            )
        }
    )
    engine = StubSimulationEngine(sc)
    sim = await engine.initialize(world, pop)
    assert sim.scenario_type == "market"
    assert all(p.role == "investor" for p in sim.personas)
    result = await engine.run(sim, sim.origin + timedelta(hours=min(4, sc.simulated_hours)))
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED
    assert "price" in result.predicted_series
    assert result.summary["scenario_type"] == "market"
    actions = {row["action"] for row in result.traces}
    assert actions <= {"buy", "sell", "hold"}
    assert "Not a real person" in sim.personas[0].notes

@pytest.mark.asyncio
async def test_mirofish_in_tree_not_configured_without_llm_keys(monkeypatch):
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    world, pop = _world()
    sc = _toy_scenario()
    engine = MiroFishEngine(sc, url=None)
    sim = await engine.initialize(world, pop)
    result = await engine.run(sim, sim.origin + timedelta(hours=sc.simulated_hours))
    assert engine.last_notes == "mirofish_in_tree_not_configured"
    assert result.summary.get("provenance_notes") == "mirofish_in_tree_not_configured"
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED


@pytest.mark.asyncio
async def test_eve_in_tree_not_configured_without_node_build(monkeypatch):
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_BIN", raising=False)
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    engine = EVEExperienceEngine(url=None)
    cand = ExperienceCandidate(
        id="exp_x",
        episode_id="episode_81",
        layer="agent",
        context={"peak_congestion": 0.6},
        observation={"stuck_n": 2},
        outcome="congestion_blocked",
    )
    val = await engine.validate(cand)
    assert engine.last_notes == "eve_in_tree_not_configured"
    assert val.counterfactuals
    assert val.counterfactuals[0].label == "model-generated"
    assert val.counterfactuals[0].fact is False

