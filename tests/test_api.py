from fastapi.testclient import TestClient

from eve_miro.api.main import app


def test_api_happy_path_create_ingest_snapshot_sim_evaluate():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    w = client.post("/worlds", json={"id": "ph-demo", "region": "philippines", "information_cutoff": "2026-08-31T10:00:00Z"})
    assert w.status_code == 200, w.text
    wid = w.json()["id"]

    ing = client.post(
        f"/worlds/{wid}/ingest",
        json={
            "providers": ["openmeteo", "usgs"],
            "window": {"start": "2024-11-01T00:00:00Z", "end": "2024-11-08T00:00:00Z"},
            "channel": "observed",
            "use_fixtures": True,
        },
    )
    assert ing.status_code == 200, ing.text
    assert ing.json()["ingested"] > 0
    assert "observed" in ing.json()["kinds"]
    assert "simulated" not in ing.json()["kinds"]

    snap = client.post(f"/worlds/{wid}/snapshot", params={"at": "2024-11-03T00:00:00Z"})
    assert snap.status_code == 200, snap.text
    body = snap.json()
    assert body["world_id"] == wid
    assert body["environment"]["weather"]

    sim = client.post(
        "/simulations",
        json={"world_id": wid, "scenario": "typhoon_manila_001", "population": 200},
    )
    assert sim.status_code == 200, sim.text
    sid = sim.json()["id"]
    assert sim.json()["provenance_kind"] == "simulated"

    run = client.post(f"/simulations/{sid}/run")
    assert run.status_code == 200, run.text
    assert run.json()["status"] in {"completed", "paused"}
    eval_id = run.json()["evaluation_id"]
    ev = client.get(f"/evaluations/{eval_id}")
    assert ev.status_code == 200, ev.text
    assert ev.json()["predicted_kind"] == "simulated"

    # explicit known-series evaluation
    posted = client.post(
        "/evaluations",
        json={
            "world_id": wid,
            "simulation_id": sid,
            "metric_name": "wind_speed_10m",
            "predicted": [10, 12, 15],
            "observed": [11, 12, 14],
        },
    )
    assert posted.status_code == 200
    assert abs(posted.json()["mae"] - 2 / 3) < 1e-9

    ex = client.get("/experiences")
    assert ex.status_code == 200
    assert ex.json()["n"] >= 1

    # provenance rejection via API
    bad = client.post(
        f"/worlds/{wid}/ingest",
        json={
            "channel": "observed",
            "events": [
                {
                    "id": "bogus-sim",
                    "source": {"provider": "fake", "dataset": "x"},
                    "observed_at": "2024-11-01T00:00:00Z",
                    "ingested_at": "2024-11-01T00:00:00Z",
                    "event_type": "weather.hourly",
                    "payload": {"wind_speed_10m": 1},
                    "provenance": {"kind": "simulated", "raw": False},
                    "temporal": {
                        "source_time": "2024-11-01T00:00:00Z",
                        "effective_time": "2024-11-01T00:00:00Z",
                        "valid_from": "2024-11-01T00:00:00Z",
                        "resolution": "hourly",
                    },
                }
            ],
        },
    )
    assert bad.status_code == 400
    assert bad.json()["error"] == "provenance"

def test_dashboard_and_extra_routes():
    from eve_miro.api.metrics_prom import reset_metrics

    reset_metrics()
    client = TestClient(app)

    dash = client.get("/")
    assert dash.status_code == 200
    html = dash.text
    assert "Reliability" in html
    assert "Load demo" in html
    assert "World" in html

    worlds0 = client.get("/worlds")
    assert worlds0.status_code == 200
    assert worlds0.json()["n"] == 0

    demo = client.post("/demo", json={"id": "ph-demo", "population": 200})
    assert demo.status_code == 200, demo.text
    body = demo.json()
    assert body["world_id"] == "ph-demo"
    assert body["ingested"] > 0
    assert body["simulation_id"]
    assert body["evaluation_id"]
    assert body["provenance_kind"] == "simulated"
    assert "SIMULATED" in body["disclaimer"]
    sid = body["simulation_id"]
    eid = body["evaluation_id"]
    wid = body["world_id"]

    worlds = client.get("/worlds")
    assert worlds.status_code == 200
    assert worlds.json()["n"] >= 1
    one = client.get(f"/worlds/{wid}")
    assert one.status_code == 200
    assert one.json()["id"] == wid

    events = client.get(f"/worlds/{wid}/events")
    assert events.status_code == 200
    row = events.json()["events"][0]
    assert "kind" in row
    assert "location" in row

    sims = client.get("/simulations")
    assert sims.status_code == 200
    assert sims.json()["n"] >= 1
    assert sims.json()["kind"] == "simulated"

    pause = client.post(f"/simulations/{sid}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "paused"
    resume = client.post(f"/simulations/{sid}/resume")
    assert resume.status_code == 200

    actions = client.get(f"/simulations/{sid}/actions")
    assert actions.status_code == 200
    posted_act = client.post(
        f"/simulations/{sid}/actions",
        json={"type": "note", "payload": {"hello": "sim"}},
    )
    assert posted_act.status_code == 200
    assert posted_act.json()["kind"] == "simulated"

    outcomes = client.get(f"/simulations/{sid}/outcomes")
    assert outcomes.status_code == 200
    assert outcomes.json()["kind"] == "simulated"

    evs = client.get("/evaluations")
    assert evs.status_code == 200
    assert evs.json()["n"] >= 1
    ev = client.get(f"/evaluations/{eid}")
    assert ev.status_code == 200
    assert ev.json()["predicted_kind"] == "simulated"

    rel = client.get(f"/reliability?world_id={wid}")
    assert rel.status_code == 200
    relj = rel.json()
    assert "sources" in relj
    assert "simulation_calibration" in relj
    assert "openmeteo" in relj["sources"]
    assert "available" in relj["sources"]["openmeteo"]

    metrics_txt = client.get("/metrics")
    assert metrics_txt.status_code == 200
    assert "eve_miro_ingest_count" in metrics_txt.text
    metrics_json = client.get("/metrics?format=json")
    assert metrics_json.status_code == 200
    mj = metrics_json.json()
    assert mj["ingest_count"] >= 1
    assert mj["sim_runs"] >= 1
    assert mj["evals"] >= 1

    exp_post = client.post(
        "/experiences",
        json={"layer": "agent", "episode_id": "test", "observation": {"stuck_n": 1}},
    )
    assert exp_post.status_code == 200, exp_post.text
    exp_id = exp_post.json()["id"]
    assert exp_post.json()["layer"] == "agent"
    val = client.post(f"/experiences/{exp_id}/validate")
    assert val.status_code == 200

    sc = client.post("/scenarios", json={"name": "adhoc_test", "note": "x"})
    assert sc.status_code == 200
    sim_sc = client.post("/scenarios/typhoon_manila_001/simulate", params={"world_id": wid})
    assert sim_sc.status_code == 200, sim_sc.text
    assert sim_sc.json()["kind"] == "simulated"

    # provenance: use first event id
    first_id = events.json()["events"][0]["id"]
    prov = client.get(f"/provenance/{first_id}", params={"world_id": wid})
    assert prov.status_code == 200, prov.text
    assert prov.json()["nodes"]


def test_health_and_metrics_empty():
    from eve_miro.api.metrics_prom import reset_metrics

    reset_metrics()
    client = TestClient(app)
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    m = client.get("/metrics?format=json")
    assert m.json()["ingest_count"] == 0
