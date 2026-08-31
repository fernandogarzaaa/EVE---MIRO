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
