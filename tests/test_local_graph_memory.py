"""Local on-disk graph memory works without ZEP_API_KEY. Offline, no Zep Cloud."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "mirofish" / "backend"
for _venv in (_REPO / "mirofish" / ".venv", _REPO / ".venv"):
    for _site in _venv.glob("lib/python*/site-packages"):
        _p = str(_site)
        if _p not in sys.path:
            sys.path.append(_p)

pytest.importorskip("flask")
pytest.importorskip("flask_cors")

_ENV_SNAPSHOT = dict(os.environ)


@pytest.fixture(scope="module", autouse=True)
def _restore_process_env_after_mirofish_imports():
    """app.config load_dotenv(override=True) must not leak into later test modules."""
    yield
    protected = {key for key in os.environ if key.startswith("PYTEST_") or key.startswith("PY_")}
    for key in list(os.environ):
        if key not in _ENV_SNAPSHOT and key not in protected:
            os.environ.pop(key, None)
    for key, value in _ENV_SNAPSHOT.items():
        os.environ[key] = value


def _load_backend():
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))
    from app import create_app
    from app.config import Config
    from app.models.project import ProjectManager, ProjectStatus
    from app.models.task import TaskManager
    from app.services.graph_builder import GraphBuilderService
    from app.services.local_graph_store import LocalGraphStore

    return {
        "create_app": create_app,
        "Config": Config,
        "ProjectManager": ProjectManager,
        "ProjectStatus": ProjectStatus,
        "TaskManager": TaskManager,
        "GraphBuilderService": GraphBuilderService,
        "LocalGraphStore": LocalGraphStore,
    }


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("MIROFISH_MEMORY", "local")
    monkeypatch.setenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", "1")
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    mods = _load_backend()
    Config = mods["Config"]
    ProjectManager = mods["ProjectManager"]
    TaskManager = mods["TaskManager"]

    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "MIROFISH_MEMORY", "local")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(uploads / "projects"))
    TaskManager._instance = None

    app = mods["create_app"]()
    app.config.update(TESTING=True)
    mods["app"] = app
    mods["uploads"] = uploads
    mods["client"] = app.test_client()
    return mods


def _seed_project(mods, *, name="Typhoon Manila"):
    ProjectManager = mods["ProjectManager"]
    ProjectStatus = mods["ProjectStatus"]
    project = ProjectManager.create_project(name=name)
    project.ontology = {
        "entity_types": [
            {"name": "Resident", "description": "A Metro Manila resident"},
            {"name": "Agency", "description": "A disaster-response agency"},
        ],
        "edge_types": [
            {
                "name": "REPORTS_TO",
                "description": "reports information to",
                "source_targets": [{"source": "Resident", "target": "Agency"}],
            }
        ],
    }
    project.status = ProjectStatus.ONTOLOGY_GENERATED
    project.simulation_requirement = "Simulate typhoon response in Metro Manila"
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(
        project.project_id,
        "Maria Santos lives in Marikina. PAGASA issued a typhoon warning. "
        "MMDA coordinates evacuation. Residents report flooding to PAGASA.",
    )
    return project


def _poll_task(client, task_id, *, timeout_s=5.0):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/graph/task/{task_id}")
        assert response.status_code == 200, response.get_data(as_text=True)
        last = response.get_json()["data"]
        status = last.get("status")
        if status == "completed":
            return last
        if status == "failed":
            pytest.fail(f"graph build failed: {last.get('error') or last.get('message')}")
        time.sleep(0.05)
    pytest.fail(f"graph build task did not complete: {last}")


def test_local_graph_build_and_entities(backend):
    mods = backend
    client = mods["client"]
    project = _seed_project(mods)

    builder = mods["GraphBuilderService"](api_key=None)
    assert builder._local is True

    response = client.post("/api/graph/build", json={"project_id": project.project_id})
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["success"] is True
    task_id = body["data"]["task_id"]

    task = _poll_task(client, task_id)
    graph_id = (task.get("result") or {}).get("graph_id")
    assert graph_id
    assert str(graph_id).startswith("local_")
    assert (task.get("result") or {}).get("node_count", 0) >= 1

    graph_path = mods["uploads"] / "local_graphs" / f"{graph_id}.json"
    assert graph_path.is_file()
    stored = json.loads(graph_path.read_text(encoding="utf-8"))
    assert stored["backend"] == "local_disk"
    assert stored.get("not_zep_cloud") is True
    assert stored.get("ontology", {}).get("entity_types")
    assert stored.get("chunks")
    assert stored.get("nodes")

    entities = client.get(f"/api/simulation/entities/{graph_id}")
    assert entities.status_code == 200, entities.get_data(as_text=True)
    payload = entities.get_json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["filtered_count"] >= 1
    assert data["entities"]
    assert data["entities"][0]["name"]
    assert any(
        label not in {"Entity", "Node"}
        for label in data["entities"][0].get("labels") or []
    )


def test_graph_build_and_entities_fail_closed_without_local_memory(tmp_path, monkeypatch):
    mods = _load_backend()
    Config = mods["Config"]
    # load_dotenv(override=True) may have restored mirofish/.env; force fail-closed.
    monkeypatch.setenv("MIROFISH_MEMORY", "")
    monkeypatch.setenv("EVE_MIRO_ALLOW_LOCAL_MEMORY", "")
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "MIROFISH_MEMORY", "")
    mods["TaskManager"]._instance = None

    app = mods["create_app"]()
    app.config.update(TESTING=True)
    client = app.test_client()

    build = client.post("/api/graph/build", json={"project_id": "proj_missing"})
    assert build.status_code == 500, build.get_data(as_text=True)
    assert build.get_json()["success"] is False

    entities = client.get("/api/simulation/entities/graph_missing")
    assert entities.status_code == 500, entities.get_data(as_text=True)
    assert entities.get_json()["success"] is False

    with pytest.raises(ValueError, match="ZEP_API_KEY"):
        mods["GraphBuilderService"](api_key=None)
