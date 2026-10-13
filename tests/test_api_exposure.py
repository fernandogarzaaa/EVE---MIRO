"""API exposure hardening: CORS, default bind host, experiment path input.

The API is unauthenticated. Before this change it (1) reflected ANY Origin
with credentials, so every web page could drive it and read responses,
(2) bound 0.0.0.0 by default, and (3) /experiments/run passed the request's
`experiment` string to load_experiment(), which opens any existing path.
"""
from fastapi.testclient import TestClient

from eve_miro.api.main import app

client = TestClient(app)


def test_cors_not_reflected_to_foreign_origin():
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_cors_allowed_for_loopback_origin():
    for origin in ("http://localhost:3000", "http://127.0.0.1:8000", "http://[::1]:5173"):
        r = client.get("/health", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") == origin, origin
        assert "access-control-allow-credentials" not in r.headers


def test_cors_lookalike_origin_rejected():
    for origin in ("http://localhost.evil.example", "http://127.0.0.1.evil.example:8000"):
        r = client.get("/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers, origin


def test_experiment_path_rejected(tmp_path):
    f = tmp_path / "private.yaml"
    f.write_text("experiment:\n  id: x\nsecret: s3cr3t\n")
    for bad in (str(f), "/etc/passwd", "../../etc/passwd", "..", "C:\\x.yaml", "typhoon/x"):
        r = client.post("/experiments/run", json={"experiment": bad, "use_fixtures": True})
        assert r.status_code == 400, (bad, r.status_code)


def test_unknown_experiment_is_404_not_500():
    r = client.post("/experiments/run", json={"experiment": "no_such_experiment", "use_fixtures": True})
    assert r.status_code == 404


def test_default_bind_is_loopback(monkeypatch):
    import uvicorn

    import importlib

    cli = importlib.import_module("eve_miro.cli.main")

    seen = {}
    monkeypatch.delenv("API_HOST", raising=False)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(k))
    assert cli.cmd_api([]) == 0
    assert seen["host"] == "127.0.0.1"
    assert cli.cmd_api(["--host", "0.0.0.0"]) == 0
    assert seen["host"] == "0.0.0.0"
