"""MiroFish HTTP client walks the real Flask routes. Never hits live Zep/LLM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from eve_miro.core.simulation.engine import StubSimulationEngine
from eve_miro.core.simulation.mirofish_client import (
    MiroFishClient,
    local_memory_allowed,
    missing_mirofish_keys,
    run_mirofish_simulation,
)
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured


def _keys(monkeypatch, *, llm="local", local_mem=True):
    monkeypatch.setenv("LLM_API_KEY", llm)
    if local_mem:
        monkeypatch.setenv("MIROFISH_MEMORY", "local")
        monkeypatch.setenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", "1")
        monkeypatch.delenv("ZEP_API_KEY", raising=False)
    else:
        monkeypatch.delenv("MIROFISH_MEMORY", raising=False)
        monkeypatch.delenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", raising=False)
    monkeypatch.setattr(
        "eve_miro.core.simulation.mirofish_client._read_dotenv", lambda path: {}
    )


def test_local_dummy_key_is_not_placeholder(monkeypatch):
    _keys(monkeypatch)
    assert missing_mirofish_keys() == []
    assert local_memory_allowed() is True


def test_missing_llm_key_fail_closed(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("MIROFISH_MEMORY", "local")
    monkeypatch.setenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", "1")
    monkeypatch.setattr(
        "eve_miro.core.simulation.mirofish_client._read_dotenv", lambda path: {}
    )
    assert "LLM_API_KEY" in missing_mirofish_keys()
    assert "ZEP_API_KEY" not in missing_mirofish_keys()


def test_zep_required_without_local_memory(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "local")
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.delenv("MIROFISH_MEMORY", raising=False)
    monkeypatch.delenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", raising=False)
    monkeypatch.setattr(
        "eve_miro.core.simulation.mirofish_client._read_dotenv", lambda path: {}
    )
    assert "ZEP_API_KEY" in missing_mirofish_keys()


def _ok(data):
    return httpx.Response(200, json={"success": True, "data": data})


def _handler(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if request.method == "POST" and path == "/api/graph/ontology/generate":
            return _ok({"project_id": "proj_1"})
        if request.method == "POST" and path == "/api/graph/build":
            return _ok({"project_id": "proj_1", "task_id": "task_1"})
        if request.method == "GET" and path == "/api/graph/task/task_1":
            return _ok({"status": "completed", "graph_id": "graph_1", "result": {"graph_id": "graph_1"}})
        if request.method == "POST" and path == "/api/simulation/create":
            return _ok({"simulation_id": "sim_1", "project_id": "proj_1", "graph_id": "graph_1"})
        if request.method == "POST" and path == "/api/simulation/prepare":
            return _ok({"simulation_id": "sim_1", "status": "ready", "already_prepared": True})
        if request.method == "POST" and path == "/api/simulation/start":
            return _ok({"simulation_id": "sim_1", "runner_status": "running"})
        if request.method == "GET" and path == "/api/simulation/sim_1/run-status":
            return _ok({"simulation_id": "sim_1", "runner_status": "completed"})
        if request.method == "GET" and path == "/api/simulation/sim_1/actions":
            return _ok(
                {
                    "count": 1,
                    "actions": [
                        {
                            "agent_id": "agent_1",
                            "action_type": "CREATE_POST",
                            "round_num": 0,
                            "platform": "twitter",
                            "success": True,
                            "result": "ok",
                        }
                    ],
                }
            )
        if request.method == "GET" and path == "/api/simulation/sim_1/timeline":
            return _ok(
                {
                    "rounds_count": 1,
                    "timeline": [
                        {
                            "round_num": 0,
                            "twitter_actions": 1,
                            "reddit_actions": 0,
                            "actions": [
                                {
                                    "agent_id": "agent_1",
                                    "action_type": "CREATE_POST",
                                    "result": "ok",
                                }
                            ],
                        }
                    ],
                }
            )
        return httpx.Response(404, json={"success": False, "error": f"unexpected {request.method} {path}"})

    return handler


@pytest.mark.asyncio
async def test_client_walks_real_flask_sequence(monkeypatch):
    _keys(monkeypatch)
    seen: list[tuple[str, str]] = []
    transport = httpx.MockTransport(_handler(seen))
    async with httpx.AsyncClient(transport=transport, base_url="http://mirofish.test") as http:
        client = MiroFishClient(
            base_url="http://mirofish.test",
            client=http,
            timeout=5,
            poll_interval=0.01,
        )
        payload = await client.run_pipeline(
            b"# seed\n",
            requirement="SIMULATED toy",
            max_rounds=1,
        )
    assert payload["project_id"] == "proj_1"
    assert payload["graph_id"] == "graph_1"
    assert payload["simulation_id"] == "sim_1"
    assert payload["actions"]
    paths = seen
    assert ("POST", "/api/graph/ontology/generate") in paths
    assert ("POST", "/api/graph/build") in paths
    assert ("GET", "/api/graph/task/task_1") in paths
    assert ("POST", "/api/simulation/create") in paths
    assert ("POST", "/api/simulation/prepare") in paths
    assert ("POST", "/api/simulation/start") in paths
    assert ("GET", "/api/simulation/sim_1/run-status") in paths
    assert ("GET", "/api/simulation/sim_1/actions") in paths
    assert ("GET", "/api/simulation/sim_1/timeline") in paths
    assert ("POST", "/api/predict") not in paths
    assert ("POST", "/simulate") not in paths
    # prepare/status is POST on the real Flask app; already_prepared skips the poll
    assert not any(p == "/api/simulation/prepare/status" and m == "GET" for m, p in paths)


@pytest.mark.asyncio
async def test_run_maps_actions_as_simulated(monkeypatch):
    _keys(monkeypatch)
    t = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    world = WorldState(world_id="w", timestamp=t, information_cutoff=t)
    pop = Population(synthetic_n=4)
    sc = Scenario(
        name="toy",
        type="typhoon",
        initial_world={"timestamp": "2026-08-31T10:00:00Z"},
        duration={"simulated_hours": 1},
        agents={"population": 4},
        random_seed=1,
        information_cutoff="2026-08-31T10:00:00Z",
    )
    engine = StubSimulationEngine(sc)
    sim = await engine.initialize(world, pop)
    seen: list[tuple[str, str]] = []
    transport = httpx.MockTransport(_handler(seen))
    async with httpx.AsyncClient(transport=transport, base_url="http://mirofish.test") as http:
        result = await run_mirofish_simulation(
            sim,
            sim.origin + timedelta(hours=1),
            url="http://mirofish.test",
            timeout=5,
            client=http,
        )
    assert result.summary["engine"] == "mirofish"
    assert result.simulation.provenance_kind is ProvenanceKind.SIMULATED
    assert result.traces
    assert all(row["provenance_kind"] == "simulated" for row in result.traces)
    assert "posts" in result.predicted_series
