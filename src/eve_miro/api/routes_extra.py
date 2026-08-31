"""Extra API routes included from main. Keep engine internals out of this module.

GET /worlds, GET /simulations, GET /evaluations, GET /metrics, GET /provenance/{id},
POST /demo, POST /experiences, POST /simulations/{id}/actions.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from eve_miro.api.metrics_prom import as_json, render_prometheus
from eve_miro.api import state as app_state
from eve_miro.api.state import WorldRecord
from eve_miro.core.experience.candidates import ExperienceCandidate
from eve_miro.core.experience.engine import get_experience_engine
from eve_miro.core.simulation.engine import StubSimulationEngine
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.projector import project_world_state
from eve_miro.core.world.provenance import ProvenanceGraph
from eve_miro.core.world.temporal import iso, utcnow

router = APIRouter()


def resolve_simulation_engine(scenario=None):
    """Call get_simulation_engine() (stub only when EVE_MIRO_ENGINES=stub)."""
    import eve_miro.core.simulation.engine as eng

    factory = getattr(eng, "get_simulation_engine", None)
    if callable(factory):
        try:
            return factory(scenario)
        except TypeError:
            inst = factory()
            if scenario is not None and hasattr(inst, "scenario"):
                inst.scenario = scenario
            return inst
    return StubSimulationEngine(scenario)


class DemoBody(BaseModel):
    id: str = "ph-demo"
    region: str = "philippines"
    information_cutoff: str = "2026-08-31T10:00:00Z"
    scenario: str = "typhoon_manila_001"
    population: int = 200
    providers: list[str] = Field(default_factory=lambda: ["openmeteo", "usgs"])


class ExperienceIn(BaseModel):
    layer: str = "agent"
    episode_id: str = "manual"
    observation: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    action: str | None = None
    outcome: str | None = None
    agent_id: str | None = None
    prediction: dict[str, Any] | None = None
    simulation_id: str | None = None


class ActionIn(BaseModel):
    type: str = "note"
    payload: dict[str, Any] = Field(default_factory=dict)


def _world_or_404(world_id: str) -> WorldRecord:
    if world_id not in app_state.STATE.worlds:
        raise HTTPException(404, f"world {world_id} not found")
    return app_state.STATE.worlds[world_id]


@router.get("/worlds")
async def list_worlds():
    rows = []
    for rec in app_state.STATE.worlds.values():
        events = app_state.STATE.store.list(rec.id)
        rows.append(
            {
                "id": rec.id,
                "region": rec.region,
                "label": rec.label,
                "created_at": iso(rec.created_at),
                "information_cutoff": iso(rec.information_cutoff) if rec.information_cutoff else None,
                "event_count": len(events),
                "kinds": sorted({e.kind.value for e in events}),
            }
        )
    return {"n": len(rows), "worlds": rows}


@router.get("/worlds/{world_id}")
async def get_world(world_id: str):
    rec = _world_or_404(world_id)
    events = app_state.STATE.store.list(world_id)
    return {
        "id": rec.id,
        "region": rec.region,
        "label": rec.label,
        "created_at": iso(rec.created_at),
        "information_cutoff": iso(rec.information_cutoff) if rec.information_cutoff else None,
        "event_count": len(events),
        "kinds": sorted({e.kind.value for e in events}),
    }


@router.get("/simulations")
async def list_simulations():
    rows = []
    for sim in app_state.STATE.simulations.values():
        rows.append(
            {
                "id": sim.id,
                "world_id": sim.world_id,
                "scenario_name": sim.scenario_name,
                "status": sim.status,
                "population_n": sim.population_n,
                "hours": sim.hours,
                "information_cutoff": iso(sim.information_cutoff),
                "provenance_kind": sim.provenance_kind.value,
                "disclaimer": sim.disclaimer,
            }
        )
    return {"n": len(rows), "simulations": rows, "kind": "simulated"}


@router.get("/evaluations")
async def list_evaluations():
    return {
        "n": len(app_state.STATE.evaluations),
        "evaluations": [e.model_dump(mode="json") for e in app_state.STATE.evaluations.values()],
    }


@router.post("/experiences")
async def post_experience(body: ExperienceIn):
    cand = ExperienceCandidate(
        id=f"exp_manual_{uuid4().hex[:10]}",
        agent_id=body.agent_id,
        episode_id=body.episode_id,
        layer=body.layer,
        context=body.context,
        prediction=body.prediction,
        action=body.action,
        observation=body.observation,
        outcome=body.outcome,
    )
    engine = get_experience_engine()
    val = await engine.validate(cand)
    app_state.STATE.experiences[val.id] = val
    return val.model_dump(mode="json")


@router.post("/simulations/{sim_id}/actions")
async def post_sim_action(sim_id: str, body: ActionIn):
    sim = app_state.STATE.simulations.get(sim_id)
    if not sim:
        raise HTTPException(404, "simulation not found")
    sim.interventions.append(
        {
            "type": body.type,
            "payload": body.payload,
            "provenance_kind": ProvenanceKind.SIMULATED.value,
            "disclaimer": sim.disclaimer,
        }
    )
    return {"id": sim_id, "n": len(sim.interventions), "kind": "simulated"}


@router.get("/metrics")
async def metrics(request: Request, format: str | None = Query(default=None)):
    accept = (request.headers.get("accept") or "").lower()
    if format == "json" or "application/json" in accept:
        return JSONResponse(as_json())
    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/provenance/{node_id}")
async def provenance_trace(node_id: str, world_id: str | None = None):
    """Walk conclusion → experience → state → event → source when a graph exists."""
    recs = [app_state.STATE.worlds[world_id]] if world_id and world_id in app_state.STATE.worlds else list(app_state.STATE.worlds.values())
    if not recs:
        raise HTTPException(404, "no world to trace; create one first")
    last_graph: ProvenanceGraph | None = None
    for rec in recs:
        events = app_state.STATE.store.list(rec.id)
        cutoff = rec.information_cutoff or utcnow()
        state = project_world_state(rec.id, events, at=cutoff, information_cutoff=cutoff, reject_leaks=False)
        graph = state.provenance_graph
        last_graph = graph
        candidates = [node_id, f"event:{node_id}", f"source:{node_id}", f"state:{node_id}"]
        node_map = graph.node_map()
        hit = next((c for c in candidates if c in node_map), None)
        if hit:
            why = graph.why(hit)
            return {
                "id": hit,
                "world_id": rec.id,
                "nodes": [n.model_dump(mode="json") for n in why],
                "sources": [n.model_dump(mode="json") for n in graph.sources_for(hit)],
                "note": "Kinds are never mixed. This trace answers why a derived state exists.",
            }
    # event lookup even if not in the folded graph
    for rec in recs:
        for e in app_state.STATE.store.list(rec.id):
            if e.id == node_id or f"event:{e.id}" == node_id:
                return {
                    "id": e.id,
                    "world_id": rec.id,
                    "kind": e.kind.value,
                    "source": e.source.model_dump(mode="json"),
                    "event_type": e.event_type,
                    "nodes": [
                        {
                            "id": f"source:{e.source.provider}:{e.source.dataset}",
                            "type": "source",
                            "label": f"{e.source.provider}/{e.source.dataset}",
                            "provenance_kind": e.kind.value,
                        },
                        {
                            "id": f"event:{e.id}",
                            "type": "event",
                            "label": e.event_type,
                            "provenance_kind": e.kind.value,
                        },
                    ],
                    "note": "Direct event→source trace.",
                }
    if last_graph is not None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": f"no provenance node {node_id}", "known": [n.id for n in last_graph.nodes[:40]]},
        )
    raise HTTPException(404, f"no provenance node {node_id}")


@router.post("/demo")
async def load_demo(body: DemoBody | None = None):
    """One-click: world → ingest openmeteo+usgs fixtures → snapshot → sim → evaluate."""
    from eve_miro.api.demo import run_demo_loop

    payload = body or DemoBody()
    return await run_demo_loop(
        world_id=payload.id,
        region=payload.region,
        information_cutoff=payload.information_cutoff,
        scenario=payload.scenario,
        population=payload.population,
        providers=payload.providers,
    )


class ExperimentRunBody(BaseModel):
    experiment: str = "typhoon_manila_closed_loop"
    use_fixtures: bool = True
    agents: int | None = None
    seeds: list[int] | None = None
    horizon: str | None = None


@router.post("/experiments/run")
async def run_experiment(body: ExperimentRunBody | None = None):
    """Closed loop: WorldState(t0) → sim → EVE → score vs WorldState(t1)."""
    import os

    from eve_miro.core.orchestration.closed_loop import ClosedLoop, split_at_cutoff
    from eve_miro.core.orchestration.experiment import load_experiment, parse_horizon
    from eve_miro.providers.common import load_fixture
    from eve_miro.providers.weather import OpenMeteoProvider

    payload = body or ExperimentRunBody()
    spec = load_experiment(payload.experiment)
    provider = OpenMeteoProvider(mode="archive")
    if payload.use_fixtures:
        os.environ.setdefault("FIXTURES", "1")
        events = provider.normalize(load_fixture("openmeteo_manila_archive.json"))
    else:
        from eve_miro.config import TimeWindow as CfgWindow

        # Live Open-Meteo: OPENMETEO_LIVE=1 or LIVE=1 or FIXTURES=0. Fail closed.
        os.environ.setdefault("OPENMETEO_LIVE", "1")
        cutoff = spec.cutoff
        window = CfgWindow(
            start=cutoff.strftime("%Y-%m-%dT00:00:00Z") if hasattr(cutoff, "strftime") else str(cutoff),
            end="2024-11-03T23:00:00Z",
        )
        events = await provider.fetch(window)
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    loop = ClosedLoop(ledger=app_state.STATE.ledger, graph=app_state.STATE.experience_graph)
    result = await loop.run(
        spec,
        app_state.STATE.store,
        t0,
        t1,
        agents=payload.agents,
        seeds=payload.seeds,
        horizon_hours=parse_horizon(payload.horizon, default=spec.horizon_hours) if payload.horizon else None,
    )
    app_state.STATE.trust_profile = result.trust_profile
    app_state.STATE.experiments[result.experiment_id] = result
    rec = app_state.STATE.worlds.get(result.world_id)
    if rec is None:
        app_state.STATE.worlds[result.world_id] = WorldRecord(
            id=result.world_id,
            created_at=utcnow(),
            information_cutoff=result.information_cutoff,
            label=result.experiment_id,
        )
    for run in result.seed_runs:
        # simulations already finished; keep ids discoverable
        app_state.STATE.scenarios.setdefault(run.simulation_id, {"experiment": result.experiment_id})
    return result.model_dump(mode="json")


@router.get("/ledger")
async def get_ledger():
    records = app_state.STATE.ledger.list()
    return {
        "n": len(records),
        "records": [r.model_dump(mode="json") for r in records],
    }


@router.get("/trust-profile")
async def get_trust_profile():
    profile = app_state.STATE.trust_profile
    if profile is None:
        from eve_miro.core.reality.trust_profile import trust_profile_from_ledger

        profile = trust_profile_from_ledger(app_state.STATE.ledger.list())
    payload = profile.model_dump(mode="json")
    payload["note"] = "Richer than /reliability. Keep /reliability. DO_NOT_USE when score is low."
    return payload
