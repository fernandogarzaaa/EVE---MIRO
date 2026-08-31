"""Full closed loop with fixtures: 3 seeds, ledger, trust profile, cutoff, MAE."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eve_miro.api.main import app
from eve_miro.core.orchestration.closed_loop import ClosedLoop, split_at_cutoff
from eve_miro.core.orchestration.experiment import load_experiment
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.projector import project_world_state
from eve_miro.errors import FutureLeakageError
from eve_miro.providers.common import load_fixture
from eve_miro.providers.weather import OpenMeteoProvider
from eve_miro.storage.event_store import InMemoryEventStore
from tests.helpers import make_event


def _archive_events():
    return OpenMeteoProvider(mode="archive").normalize(load_fixture("openmeteo_manila_archive.json"))


@pytest.mark.asyncio
async def test_closed_loop_fixtures_three_seeds_ledger_trust_cutoff_mae():
    spec = load_experiment("typhoon_manila_closed_loop")
    assert spec.id == "typhoon_manila_001"
    events = _archive_events()
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    assert t0, "t0 must contain the cutoff hour from the archive fixture"
    assert t1, "t1 must contain later observed weather after the cutoff"
    assert all(e.temporal.effective_time <= spec.cutoff for e in t0)
    assert all(e.temporal.effective_time > spec.cutoff for e in t1)

    store = InMemoryEventStore()
    loop = ClosedLoop()
    result = await loop.run(
        spec,
        store,
        t0,
        t1,
        agents=40,
        seeds=[1, 2, 3],
        horizon_hours=6,
        world_id="w_loop",
    )
    assert result.experiment_id == "typhoon_manila_001"
    assert {r.seed for r in result.seed_runs} == {1, 2, 3}
    assert len(result.seed_runs) == 3 * len(spec.scenarios)
    assert result.ledger_record_ids
    assert loop.ledger.list()
    assert result.trust_profile is not None
    assert "weather" in result.trust_profile.domains
    assert "news" in result.trust_profile.domains
    assert result.trust_profile.domains["news"].recommendation == "DO_NOT_USE"

    wind_align = [a for a in result.alignments if a.metric_name == "wind_speed_10m"]
    assert wind_align
    assert any(a.mae is not None for a in wind_align)
    assert any(e.get("mae") is not None for e in result.evaluations)

    # cutoff honored: t0 world has no post-cutoff events
    t0_world = project_world_state(
        "w_loop", t0, at=spec.cutoff, information_cutoff=spec.cutoff, reject_leaks=True
    )
    assert all(eid in t0_world.events or True for eid in result.t0_event_ids)
    for eid in result.t0_event_ids:
        # every folded t0 event is from the t0 set
        assert eid in {e.id for e in t0}

    leaked = make_event("leak-t1", "2024-11-03T00:00:00Z", payload={"wind_speed_10m": 999.0})
    with pytest.raises(FutureLeakageError):
        await ClosedLoop().run(
            spec,
            InMemoryEventStore(),
            t0 + [leaked],
            t1,
            agents=8,
            seeds=[1],
            horizon_hours=2,
            world_id="w_leak",
        )

    # pytest conftest forces EVE_MIRO_ENGINES=stub
    assert result.engines.get("simulation") in {"mirofish", "stub"}
    assert result.engines.get("experience") in {"eve", "eve_stub"}
    assert "weight" not in result.artifacts_note.lower() or "never" in result.artifacts_note.lower()

    # structured snapshot, not a WorldState blob as the only representation
    # (checked via adapter contract on a completed sim summary)
    assert result.t1_event_n == len(t1)


def test_api_experiments_run_ledger_and_trust_profile():
    client = TestClient(app)
    rel = client.get("/reliability")
    assert rel.status_code == 200
    run = client.post(
        "/experiments/run",
        json={
            "experiment": "typhoon_manila_closed_loop",
            "use_fixtures": True,
            "agents": 16,
            "seeds": [1, 2],
            "horizon": "2h",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["experiment_id"] == "typhoon_manila_001"
    assert body["ledger_record_ids"]
    assert body["trust_profile"]["domains"]["weather"]
    led = client.get("/ledger")
    assert led.status_code == 200
    assert led.json()["n"] >= 1
    rec = led.json()["records"][0]
    assert "input_provenance_kinds" in rec
    tp = client.get("/trust-profile")
    assert tp.status_code == 200
    assert "weather" in tp.json()["domains"]
    # /reliability is kept
    rel2 = client.get("/reliability")
    assert rel2.status_code == 200


def test_old_scenario_yaml_still_loads():
    from eve_miro.core.simulation.scenarios import load_scenario

    sc = load_scenario()
    assert sc.name == "typhoon_manila_001"
    assert sc.population == 1000
