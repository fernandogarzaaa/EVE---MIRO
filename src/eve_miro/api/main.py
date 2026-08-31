"""FastAPI entrypoint.

Run: uvicorn eve_miro.api.main:app --reload --port 8000
The layout folder apps/api is a pointer; this module is the real app.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from eve_miro import __version__
from eve_miro.api.state import STATE, WorldRecord, reset_state
from eve_miro.config import PHILIPPINES, PROVIDER_INTERVALS
from eve_miro.core.evaluation.reality_check import Evaluation, reality_check, reliability_from_freshness
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.simulation.engine import StubSimulationEngine
from eve_miro.core.simulation.orchestration import run_scenario
from eve_miro.core.simulation.scenarios import load_scenario
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.projector import project_world_state
from eve_miro.core.world.state import Population
from eve_miro.core.world.temporal import as_utc, iso, utcnow
from eve_miro.errors import EveMiroError, FutureLeakageError, ProvenanceError, ReplayError
from eve_miro.providers.protocol import TimeWindow
from eve_miro.providers.registry import all_providers
from eve_miro.worker.loop import ingest_from_providers, provider_cadence

STATIC = Path(__file__).resolve().parent / "static"
DASHBOARD = Path(__file__).resolve().parents[3] / "apps" / "dashboard"

app = FastAPI(
    title="EVE-MIRO",
    version=__version__,
    description="Reality-grounded experiential simulation. Provenance kinds are never mixed.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.exception_handler(ProvenanceError)
async def _prov(_req, exc: ProvenanceError):
    return JSONResponse(status_code=400, content={"error": "provenance", "detail": str(exc)})


@app.exception_handler(FutureLeakageError)
async def _leak(_req, exc: FutureLeakageError):
    return JSONResponse(status_code=400, content={"error": "future_leakage", "detail": str(exc)})


@app.exception_handler(ReplayError)
async def _replay(_req, exc: ReplayError):
    return JSONResponse(status_code=400, content={"error": "replay", "detail": str(exc)})


class CreateWorldBody(BaseModel):
    id: str | None = None
    region: str = "philippines"
    information_cutoff: str | None = None
    label: str = ""


class IngestBody(BaseModel):
    events: list[dict[str, Any]] | None = None
    providers: list[str] | None = None
    window: dict[str, str] | None = None
    channel: ProvenanceKind = ProvenanceKind.OBSERVED
    use_fixtures: bool = True


class CreateSimBody(BaseModel):
    world_id: str
    scenario: str | None = "typhoon_manila_001"
    population: int | None = None
    seed: int | None = None


class EvaluateBody(BaseModel):
    world_id: str
    simulation_id: str
    metric_name: str = "wind_speed_10m"
    predicted: list[float] | None = None
    observed: list[float] | None = None


def _world_or_404(world_id: str) -> WorldRecord:
    if world_id not in STATE.worlds:
        raise HTTPException(404, f"world {world_id} not found")
    return STATE.worlds[world_id]


@app.get("/health")
async def health():
    providers = {}
    for name, p in all_providers().items():
        h = await p.health()
        providers[name] = h.model_dump(mode="json")
        providers[name]["interval"] = str(PROVIDER_INTERVALS.get(name, ""))
    return {
        "status": "ok",
        "version": __version__,
        "providers": providers,
        "cadence": provider_cadence(),
        "store": type(STATE.store).__name__,
    }


@app.get("/reliability")
async def reliability(world_id: str | None = None):
    now = utcnow()
    freshness: dict[str, dict[str, Any]] = {}
    events = []
    if world_id and world_id in STATE.worlds:
        events = STATE.store.list(world_id)
    by_src: dict[str, list] = {}
    for e in events:
        by_src.setdefault(e.source.provider, []).append(e)
    for name in list(all_providers()):
        rows = by_src.get(name, [])
        last = max((e.temporal.effective_time for e in rows), default=None)
        age = (now - last).total_seconds() if last else None
        freshness[name] = {
            "event_count": len(rows),
            "last_effective_time": iso(last) if last else None,
            "age_seconds": age,
            "complete": len(rows) > 0,
            "interval_seconds": PROVIDER_INTERVALS.get(name, timedelta(hours=24)).total_seconds(),
        }
    report = reliability_from_freshness(freshness)
    return report.model_dump(mode="json")


@app.post("/worlds")
async def create_world(body: CreateWorldBody):
    wid = body.id or f"world_{uuid4().hex[:10]}"
    rec = WorldRecord(
        id=wid,
        created_at=utcnow(),
        region=body.region,
        information_cutoff=as_utc(body.information_cutoff) if body.information_cutoff else None,
        label=body.label,
    )
    STATE.worlds[wid] = rec
    return {"id": wid, "region": rec.region, "information_cutoff": iso(rec.information_cutoff) if rec.information_cutoff else None}


@app.post("/worlds/{world_id}/ingest")
async def ingest(world_id: str, body: IngestBody):
    rec = _world_or_404(world_id)
    if body.use_fixtures:
        os.environ.setdefault("FIXTURES", "1")
    accepted: list[WorldEvent] = []
    cutoff = rec.information_cutoff
    if body.events:
        events = [WorldEvent.model_validate(e) for e in body.events]
        accepted.extend(
            STATE.store.append_many(world_id, events, channel=body.channel, information_cutoff=cutoff)
        )
    if body.providers:
        window_raw = body.window or {
            "start": "2024-11-01T00:00:00Z",
            "end": "2024-11-03T23:00:00Z",
        }
        window = TimeWindow(start=window_raw["start"], end=window_raw["end"], region=rec.region)
        accepted.extend(
            await ingest_from_providers(
                STATE.store,
                world_id,
                body.providers,
                window,
                channel=body.channel,
                information_cutoff=cutoff,
            )
        )
    kinds = sorted({e.kind.value for e in accepted})
    return {
        "ingested": len(accepted),
        "ids": [e.id for e in accepted[:50]],
        "kinds": kinds,
        "note": "Provenance kinds are never mixed. Simulated data cannot be ingested as observed.",
    }


@app.post("/worlds/{world_id}/snapshot")
async def snapshot(world_id: str, at: str | None = None):
    rec = _world_or_404(world_id)
    when = as_utc(at) if at else utcnow()
    cutoff = rec.information_cutoff or when
    events = STATE.store.list(world_id)
    state = project_world_state(world_id, events, at=when, information_cutoff=cutoff, reject_leaks=False)
    return state.model_dump(mode="json")


@app.get("/worlds/{world_id}/state")
async def get_state(world_id: str, at: str | None = None):
    return await snapshot(world_id, at=at)


@app.get("/worlds/{world_id}/events")
async def list_events(world_id: str):
    _world_or_404(world_id)
    events = STATE.store.list(world_id)
    return {
        "n": len(events),
        "events": [
            {
                "id": e.id,
                "source": e.source.model_dump(),
                "event_type": e.event_type,
                "observed_at": iso(e.observed_at),
                "kind": e.kind.value,
                "freshness": iso(e.temporal.effective_time),
                "payload_keys": list(e.payload.keys()),
            }
            for e in events
        ],
    }


@app.post("/simulations")
async def create_sim(body: CreateSimBody):
    rec = _world_or_404(body.world_id)
    scenario = load_scenario(name=body.scenario) if body.scenario else None
    if scenario and body.population:
        scenario.agents["population"] = body.population
    if scenario and body.seed is not None:
        scenario.random_seed = body.seed
    cutoff = rec.information_cutoff or (scenario.cutoff if scenario else utcnow())
    events = STATE.store.list(body.world_id)
    world = project_world_state(body.world_id, events, at=cutoff, information_cutoff=cutoff)
    n = body.population or (scenario.population if scenario else 200)
    engine = StubSimulationEngine(scenario)
    sim = await engine.initialize(world, Population(synthetic_n=n))
    STATE.simulations[sim.id] = sim
    STATE.scenarios[sim.id] = {"engine": engine, "scenario": scenario}
    return {
        "id": sim.id,
        "status": sim.status,
        "population_n": sim.population_n,
        "hours": sim.hours,
        "information_cutoff": iso(sim.information_cutoff),
        "provenance_kind": sim.provenance_kind.value,
        "disclaimer": sim.disclaimer,
    }


@app.get("/simulations/{sim_id}")
async def get_sim(sim_id: str):
    sim = STATE.simulations.get(sim_id)
    if not sim:
        raise HTTPException(404, "simulation not found")
    return sim.model_dump(mode="json", exclude={"personas", "steps"}) | {
        "steps_n": len(sim.steps),
        "personas_n": len(sim.personas),
    }


@app.post("/simulations/{sim_id}/run")
async def run_sim(sim_id: str):
    sim = STATE.simulations.get(sim_id)
    if not sim:
        raise HTTPException(404, "simulation not found")
    pack = STATE.scenarios.get(sim_id) or {}
    engine: StubSimulationEngine = pack.get("engine") or StubSimulationEngine()
    until = sim.origin + timedelta(hours=sim.hours)
    result = await engine.run(sim, until)
    STATE.results[sim_id] = result
    # experiences
    from eve_miro.core.experience.candidates import Trajectory

    exp_engine = StubExperienceEngine()
    traj = Trajectory(simulation_id=sim.id, actions=result.traces, predicted_series=result.predicted_series)
    for cand in await exp_engine.observe(traj):
        val = await exp_engine.validate(cand)
        STATE.experiences[val.id] = val
    # auto reality-check against observed weather in the world if present
    events = STATE.store.list(sim.world_id, kinds=[ProvenanceKind.OBSERVED])
    obs_w = []
    obs_t = []
    for e in events:
        if e.event_type.startswith("weather") and e.payload.get("wind_speed_10m") is not None:
            obs_t.append(iso(e.temporal.effective_time))
            obs_w.append(float(e.payload["wind_speed_10m"]))
    pred = result.predicted_series.get("wind_speed_10m") or []
    ev = reality_check(
        world_id=sim.world_id,
        simulation_id=sim.id,
        predicted=pred,
        observed=obs_w,
        pred_times=result.predicted_times,
        obs_times=obs_t,
        metric_name="wind_speed_10m",
    )
    STATE.evaluations[ev.id] = ev
    result.summary["evaluation_id"] = ev.id
    return {
        "id": sim.id,
        "status": sim.status,
        "summary": result.summary,
        "evaluation_id": ev.id,
        "provenance_kind": "simulated",
    }


@app.post("/simulations/{sim_id}/pause")
async def pause_sim(sim_id: str):
    sim = STATE.simulations.get(sim_id)
    if not sim:
        raise HTTPException(404, "simulation not found")
    sim.status = "paused"
    return {"id": sim_id, "status": sim.status}


@app.post("/simulations/{sim_id}/resume")
async def resume_sim(sim_id: str):
    sim = STATE.simulations.get(sim_id)
    if not sim:
        raise HTTPException(404, "simulation not found")
    sim.status = "running"
    return {"id": sim_id, "status": sim.status}


@app.get("/simulations/{sim_id}/actions")
async def sim_actions(sim_id: str, limit: int = 200):
    result = STATE.results.get(sim_id)
    if not result:
        raise HTTPException(404, "run the simulation first")
    return {"n": len(result.traces), "actions": result.traces[:limit], "kind": "simulated"}


@app.get("/simulations/{sim_id}/outcomes")
async def sim_outcomes(sim_id: str):
    result = STATE.results.get(sim_id)
    if not result:
        raise HTTPException(404, "run the simulation first")
    return {"summary": result.summary, "predicted_series": result.predicted_series, "kind": "simulated"}


@app.get("/experiences")
async def list_exp():
    return {
        "n": len(STATE.experiences),
        "experiences": [e.model_dump(mode="json") for e in STATE.experiences.values()],
    }


@app.get("/experiences/{exp_id}")
async def get_exp(exp_id: str):
    e = STATE.experiences.get(exp_id)
    if not e:
        raise HTTPException(404, "experience not found")
    return e.model_dump(mode="json")


@app.post("/experiences/{exp_id}/validate")
async def validate_exp(exp_id: str):
    e = STATE.experiences.get(exp_id)
    if not e:
        raise HTTPException(404, "experience not found")
    engine = StubExperienceEngine()
    val = await engine.validate(e.candidate)
    STATE.experiences[val.id] = val
    return val.model_dump(mode="json")


@app.post("/scenarios")
async def post_scenario(payload: dict[str, Any]):
    name = payload.get("name") or f"scenario_{uuid4().hex[:8]}"
    STATE.scenarios[name] = payload
    return {"id": name, "stored": True}


@app.post("/scenarios/{scenario_id}/simulate")
async def simulate_scenario(scenario_id: str, world_id: str | None = None):
    if scenario_id == "typhoon_manila_001" or scenario_id not in STATE.worlds:
        scenario = load_scenario(name="typhoon_manila_001")
    else:
        scenario = load_scenario(name=scenario_id)
    wid = world_id or next(iter(STATE.worlds), None)
    if not wid:
        rec = WorldRecord(id=f"world_{uuid4().hex[:10]}", created_at=utcnow(), information_cutoff=scenario.cutoff)
        STATE.worlds[rec.id] = rec
        wid = rec.id
    events = STATE.store.list(wid)
    result, selected = await run_scenario(wid, events, scenario)
    STATE.simulations[result.simulation.id] = result.simulation
    STATE.results[result.simulation.id] = result
    for v in selected:
        STATE.experiences[v.id] = v
    return {
        "simulation_id": result.simulation.id,
        "summary": result.summary,
        "experiences": [v.id for v in selected],
        "kind": "simulated",
    }


@app.get("/evaluations/{eval_id}")
async def get_eval(eval_id: str):
    e = STATE.evaluations.get(eval_id)
    if not e:
        raise HTTPException(404, "evaluation not found")
    return e.model_dump(mode="json")


@app.post("/evaluations")
async def post_eval(body: EvaluateBody):
    sim = STATE.simulations.get(body.simulation_id)
    result = STATE.results.get(body.simulation_id)
    predicted = body.predicted
    if predicted is None and result:
        predicted = result.predicted_series.get(body.metric_name) or result.predicted_series.get("wind_speed_10m") or []
    observed = body.observed or []
    ev = reality_check(
        world_id=body.world_id,
        simulation_id=body.simulation_id,
        predicted=predicted or [],
        observed=observed,
        metric_name=body.metric_name,
    )
    STATE.evaluations[ev.id] = ev
    return ev.model_dump(mode="json")


def _dashboard_html() -> str:
    for candidate in (DASHBOARD / "index.html", STATIC / "index.html"):
        if candidate.exists():
            return candidate.read_text()
    return "<h1>EVE-MIRO</h1><p>Dashboard file missing.</p>"


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(_dashboard_html())


def run() -> None:
    import uvicorn

    uvicorn.run("eve_miro.api.main:app", host=os.environ.get("API_HOST", "0.0.0.0"), port=int(os.environ.get("API_PORT", "8000")))
