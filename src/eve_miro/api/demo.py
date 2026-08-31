"""Tiny local demo helper. Prints the happy-path curl sequence and runs it in-process."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from eve_miro.api.metrics_prom import inc_eval, inc_ingest, inc_sim_run
from eve_miro.api import state as app_state
from eve_miro.api.state import WorldRecord
from eve_miro.core.evaluation.reality_check import reality_check
from eve_miro.core.experience.candidates import Trajectory
from eve_miro.core.experience.engine import StubExperienceEngine
from eve_miro.core.simulation.scenarios import load_scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.projector import project_world_state
from eve_miro.core.world.state import Population
from eve_miro.core.world.temporal import as_utc, iso, utcnow
from eve_miro.providers.protocol import TimeWindow
from eve_miro.worker.loop import ingest_from_providers


async def run_demo_loop(
    *,
    world_id: str = "ph-demo",
    region: str = "philippines",
    information_cutoff: str = "2026-08-31T10:00:00Z",
    scenario: str = "typhoon_manila_001",
    population: int = 200,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """POST /worlds, ingest openmeteo+usgs fixtures, snapshot, run sim, evaluate."""
    os.environ.setdefault("FIXTURES", "1")
    providers = providers or ["openmeteo", "usgs"]
    cutoff = as_utc(information_cutoff)
    rec = app_state.STATE.worlds.get(world_id)
    if rec is None:
        rec = WorldRecord(
            id=world_id,
            created_at=utcnow(),
            region=region,
            information_cutoff=cutoff,
            label="Load demo — Philippines first domain",
        )
        app_state.STATE.worlds[world_id] = rec
    else:
        rec.information_cutoff = rec.information_cutoff or cutoff

    window = TimeWindow(start="2024-11-01T00:00:00Z", end="2024-11-08T00:00:00Z", region=rec.region)
    accepted = await ingest_from_providers(
        app_state.STATE.store,
        world_id,
        providers,
        window,
        channel=ProvenanceKind.OBSERVED,
        information_cutoff=rec.information_cutoff,
    )
    inc_ingest(len(accepted))

    events = app_state.STATE.store.list(world_id)
    snap_at = rec.information_cutoff or utcnow()
    state = project_world_state(world_id, events, at=snap_at, information_cutoff=snap_at, reject_leaks=False)

    from eve_miro.api.routes_extra import resolve_simulation_engine

    sc = load_scenario(name=scenario) if scenario else None
    if sc and population:
        sc.agents["population"] = population
    n = population or (sc.population if sc else 200)
    engine = resolve_simulation_engine(sc)
    sim = await engine.initialize(state, Population(synthetic_n=n))
    app_state.STATE.simulations[sim.id] = sim
    app_state.STATE.scenarios[sim.id] = {"engine": engine, "scenario": sc}

    until = sim.origin + timedelta(hours=sim.hours)
    result = await engine.run(sim, until)
    app_state.STATE.results[sim.id] = result
    inc_sim_run()

    exp_engine = StubExperienceEngine()
    traj = Trajectory(simulation_id=sim.id, actions=result.traces, predicted_series=result.predicted_series)
    experience_ids: list[str] = []
    for cand in await exp_engine.observe(traj):
        val = await exp_engine.validate(cand)
        app_state.STATE.experiences[val.id] = val
        experience_ids.append(val.id)

    obs_w: list[float] = []
    obs_t: list[str] = []
    for e in app_state.STATE.store.list(sim.world_id, kinds=[ProvenanceKind.OBSERVED]):
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
    app_state.STATE.evaluations[ev.id] = ev
    result.summary["evaluation_id"] = ev.id
    inc_eval()

    return {
        "world_id": world_id,
        "simulation_id": sim.id,
        "evaluation_id": ev.id,
        "experience_ids": experience_ids,
        "ingested": len(accepted),
        "kinds": sorted({e.kind.value for e in accepted}),
        "status": sim.status,
        "population_n": sim.population_n,
        "information_cutoff": iso(sim.information_cutoff),
        "snapshot_event_count": state.quality.get("event_count"),
        "disclaimer": sim.disclaimer,
        "provenance_kind": "simulated",
        "mae": ev.mae,
        "rmse": ev.rmse,
        "domain_trusted": ev.domain_trusted,
        "notes": ev.notes,
    }


def main() -> None:
    print(
        """
# terminal 1
FIXTURES=1 python3 -m uvicorn eve_miro.api.main:app --port 8000

# terminal 2 — one-click (same as the dashboard Load demo button)
curl -s -X POST localhost:8000/demo -H 'content-type: application/json' -d '{}'

# or the long form:
curl -s -X POST localhost:8000/worlds -H 'content-type: application/json' \\
  -d '{"id":"ph-demo","information_cutoff":"2026-08-31T10:00:00Z"}'
curl -s -X POST localhost:8000/worlds/ph-demo/ingest -H 'content-type: application/json' \\
  -d '{"providers":["openmeteo","usgs"],"use_fixtures":true}'
curl -s localhost:8000/worlds/ph-demo/state
curl -s -X POST localhost:8000/simulations -H 'content-type: application/json' \\
  -d '{"world_id":"ph-demo","scenario":"typhoon_manila_001","population":200}'
# then POST /simulations/{id}/run
open http://127.0.0.1:8000/
"""
    )


if __name__ == "__main__":
    main()
