"""In-tree engines raise EngineNotConfigured instead of silently stubbing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from eve_miro.api.main import app
from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.eve_adapter import EVEExperienceEngine
from eve_miro.core.orchestration.closed_loop import ClosedLoop, split_at_cutoff
from eve_miro.core.orchestration.experiment import load_experiment
from eve_miro.core.simulation.mirofish_adapter import MiroFishEngine
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured
from eve_miro.providers.common import load_fixture
from eve_miro.providers.weather import OpenMeteoProvider
from eve_miro.storage.event_store import InMemoryEventStore


def _isolate_keys(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("MIROFISH_MEMORY", raising=False)
    monkeypatch.delenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", raising=False)
    monkeypatch.delenv("MIROFISH_URL", raising=False)
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_BIN", raising=False)
    monkeypatch.setattr(
        "eve_miro.core.simulation.mirofish_client._read_dotenv", lambda path: {}
    )


@pytest.mark.asyncio
async def test_closed_loop_raises_without_keys(monkeypatch):
    _isolate_keys(monkeypatch)
    spec = load_experiment("typhoon_manila_closed_loop")
    events = OpenMeteoProvider(mode="archive").normalize(load_fixture("openmeteo_manila_archive.json"))
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    with pytest.raises(EngineNotConfigured, match="LLM_API_KEY"):
        await ClosedLoop().run(
            spec,
            InMemoryEventStore(),
            t0,
            t1,
            agents=8,
            seeds=[1],
            horizon_hours=1,
            world_id="w_fail_closed",
        )


def test_api_experiments_run_returns_503_when_in_tree_unconfigured(monkeypatch):
    _isolate_keys(monkeypatch)
    client = TestClient(app)
    run = client.post(
        "/experiments/run",
        json={
            "experiment": "typhoon_manila_closed_loop",
            "use_fixtures": True,
            "agents": 8,
            "seeds": [1],
            "horizon": "1h",
        },
    )
    assert run.status_code == 503, run.text
    body = run.json()
    assert body["error"] == "engine_not_configured"
    assert "LLM_API_KEY" in body["detail"]


@pytest.mark.asyncio
async def test_eve_validate_raises_when_cli_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    monkeypatch.setenv("EVE_ROOT", str(tmp_path / "eve"))
    monkeypatch.delenv("EVE_URL", raising=False)
    monkeypatch.delenv("EVE_BIN", raising=False)
    (tmp_path / "eve").mkdir()
    engine = EVEExperienceEngine(url=None, timeout=0.2)
    cand = ExperienceCandidate(
        id="exp_x",
        episode_id="episode_81",
        layer="agent",
        context={"peak_congestion": 0.6},
        observation={"stuck_n": 2},
        outcome="congestion_blocked",
    )
    with pytest.raises(EngineNotConfigured, match="EVE CLI is not built"):
        await engine.validate(cand)


@pytest.mark.asyncio
async def test_eve_validate_maps_subprocess_json(monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    payload = {
        "id": "exp_x",
        "validity": 0.81,
        "confidence": 0.7,
        "prediction_error": 0.2,
        "learning_value": 0.55,
        "transferability": 0.4,
        "retention_score": 0.3,
        "counterfactuals": [
            {
                "id": "cf_1",
                "intervention": "issue warning earlier",
                "predicted_delta": {"stuck_rate": -0.2},
                "label": "model-generated",
                "fact": False,
            }
        ],
        "applicability": ["philippines"],
        "layer": "agent",
    }

    def fake_run(*_a, **_k):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode(), stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "eve_miro.core.experience.eve_adapter.eve_trajectory_command",
        lambda **kwargs: ["node", "eve.js", "trajectory", "--stdin"],
    )
    engine = EVEExperienceEngine(url=None, timeout=0.2)
    cand = ExperienceCandidate(
        id="exp_x",
        episode_id="episode_81",
        layer="agent",
        context={"peak_congestion": 0.6},
        observation={"stuck_n": 2},
        outcome="congestion_blocked",
    )
    val = await engine.validate(cand)
    assert val.validity == 0.81
    assert val.confidence == 0.7
    assert val.counterfactuals
    assert val.counterfactuals[0].label == "model-generated"
    assert val.counterfactuals[0].fact is False
    assert engine.last_notes == "eve"


@pytest.mark.asyncio
async def test_mirofish_step_raises():
    t = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    world = WorldState(world_id="w", timestamp=t, information_cutoff=t)
    pop = Population(synthetic_n=2)
    sc = Scenario(
        name="toy",
        type="typhoon",
        initial_world={"timestamp": "2026-08-31T10:00:00Z"},
        duration={"simulated_hours": 1},
        agents={"population": 2},
        random_seed=1,
        information_cutoff="2026-08-31T10:00:00Z",
    )
    engine = MiroFishEngine(sc, url=None)
    sim = await engine.initialize(world, pop)
    with pytest.raises(EngineNotConfigured, match="does not support step"):
        await engine.step(sim)


@pytest.mark.asyncio
async def test_eve_observe_is_labeled_local_heuristic():
    from eve_miro.core.experience.candidates import Trajectory
    from eve_miro.core.experience.eve_adapter import EVEExperienceEngine

    engine = EVEExperienceEngine(url=None, timeout=0.2)
    cands = await engine.observe(
        Trajectory(simulation_id="sim_h", actions=[{"action": "CREATE_POST", "agent_id": "a1", "hour": 0}])
    )
    assert cands
    assert all(c.provenance.get("engine") == "local-heuristic" for c in cands)
