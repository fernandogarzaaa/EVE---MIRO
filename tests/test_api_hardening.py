from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from eve_miro.api.main import app
from eve_miro.providers import common


def test_fixture_mode_overrides_process_default(monkeypatch):
    monkeypatch.setenv("FIXTURES", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("TEST_PROVIDER_LIVE", "0")
    monkeypatch.setattr(common, "load_fixture", lambda name: {"source": "fixture"})

    async def live_factory():
        return {"source": "live"}

    async def exercise():
        with common.fixture_mode(False):
            live = await common.fetch_live_or_fixture(
                "TEST_PROVIDER_LIVE", "example.json", live_factory
            )
        with common.fixture_mode(True):
            fixture = await common.fetch_live_or_fixture(
                "TEST_PROVIDER_LIVE", "example.json", live_factory
            )
        return live, fixture

    live, fixture = asyncio.run(exercise())
    assert live == {"source": "live"}
    assert fixture == {"source": "fixture"}


def test_duplicate_world_id_is_conflict():
    client = TestClient(app)
    world_id = "hardening-duplicate-world"
    first = client.post("/worlds", json={"id": world_id})
    assert first.status_code == 200, first.text

    duplicate = client.post("/worlds", json={"id": world_id})
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_unknown_scenario_does_not_silently_run_typhoon_default():
    client = TestClient(app)
    response = client.post("/scenarios/not-a-real-scenario/simulate")
    assert response.status_code == 404
    assert "scenario not found" in response.json()["detail"]


def test_simulation_population_must_be_positive_and_bounded():
    client = TestClient(app)
    zero = client.post("/simulations", json={"world_id": "not-used", "population": 0})
    too_large = client.post("/simulations", json={"world_id": "not-used", "population": 100001})
    assert zero.status_code == 422
    assert too_large.status_code == 422


def test_scenario_name_rejects_path_like_input():
    client = TestClient(app)
    response = client.post("/scenarios", json={"name": "../secrets"})
    assert response.status_code == 400
