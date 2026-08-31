"""ClosedLoop: WorldState(t0) → MiroFish-shaped sim → EVE → score vs WorldState(t1).

Uses SimulationEngine / ExperienceEngine protocols. EVE and MiroFish do not
import each other's internals. When EVE_MIRO_ENGINES=stub the factories
return stubs. Otherwise EngineNotConfigured is raised — never a silent stub.
On success, engines report ``mirofish`` / ``eve``.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

from eve_miro.core.experience.engine import get_experience_engine
from eve_miro.core.experience.graph import ExperienceGraph, fingerprint_of
from eve_miro.core.orchestration.experiment import (
    ExperimentSpec,
    intervention_timestamp,
    load_experiment,
    parse_horizon,
)
from eve_miro.core.orchestration.miro_to_eve import observe_and_validate
from eve_miro.core.orchestration.reality_alignment import Alignment, RealityAligner
from eve_miro.core.orchestration.world_to_miro import MiroWorldAdapter
from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.reality.trust_profile import TrustProfile, trust_profile_from_ledger
from eve_miro.core.simulation.engine import get_simulation_engine
from eve_miro.core.simulation.observation import perceive_population
from eve_miro.core.simulation.scenarios import Intervention, Scenario
from eve_miro.core.simulation.trajectory import agent_trajectories_from_result
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.projector import project_world_state
from eve_miro.core.world.state import Population
from eve_miro.core.world.temporal import as_utc, iso
from eve_miro.storage.event_store import EventStore, InMemoryEventStore


def split_at_cutoff(
    events: Sequence[WorldEvent],
    cutoff: datetime | str,
) -> tuple[list[WorldEvent], list[WorldEvent]]:
    cut = as_utc(cutoff)
    t0: list[WorldEvent] = []
    t1: list[WorldEvent] = []
    for event in events:
        if as_utc(event.temporal.effective_time) <= cut:
            t0.append(event)
        else:
            t1.append(event)
    return t0, t1


def summarize_scalar(values: Sequence[float]) -> dict[str, Any]:
    xs = [float(v) for v in values]
    n = len(xs)
    if n == 0:
        return {"mean": None, "variance": None, "interval": [None, None], "n": 0}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    std = math.sqrt(var)
    se = std / math.sqrt(n) if n else 0.0
    return {
        "mean": mean,
        "variance": var,
        "interval": [mean - 1.96 * se, mean + 1.96 * se],
        "n": n,
    }


def mean_series(series_list: Sequence[Sequence[float]]) -> list[float]:
    if not series_list:
        return []
    length = min(len(s) for s in series_list)
    if length == 0:
        return []
    out: list[float] = []
    for i in range(length):
        out.append(sum(float(s[i]) for s in series_list) / len(series_list))
    return out


def variance_series(series_list: Sequence[Sequence[float]]) -> list[float]:
    if not series_list:
        return []
    length = min(len(s) for s in series_list)
    means = mean_series([s[:length] for s in series_list])
    n = len(series_list)
    out: list[float] = []
    for i in range(length):
        m = means[i]
        out.append(sum((float(s[i]) - m) ** 2 for s in series_list) / n)
    return out


class SeedRun(BaseModel):
    scenario_id: str
    seed: int
    simulation_id: str
    summary: dict[str, Any] = Field(default_factory=dict)
    predicted_series: dict[str, list[float]] = Field(default_factory=dict)
    predicted_times: list[str] = Field(default_factory=list)
    evacuation_rate: float = 0.0
    peak_wind: float = 0.0
    peak_congestion: float = 0.0
    experience_ids: list[str] = Field(default_factory=list)
    engine_notes: str | None = None


class ScenarioAggregate(BaseModel):
    scenario_id: str
    n_seeds: int
    evacuation_rate: dict[str, Any] = Field(default_factory=dict)
    peak_wind: dict[str, Any] = Field(default_factory=dict)
    peak_congestion: dict[str, Any] = Field(default_factory=dict)
    wind_speed_10m: dict[str, Any] = Field(default_factory=dict)
    mean_predicted_series: dict[str, list[float]] = Field(default_factory=dict)
    mean_predicted_times: list[str] = Field(default_factory=list)


class ClosedLoopResult(BaseModel):
    experiment_id: str
    world_id: str
    information_cutoff: datetime
    t0_timestamp: datetime
    seed_runs: list[SeedRun] = Field(default_factory=list)
    aggregates: dict[str, ScenarioAggregate] = Field(default_factory=dict)
    alignments: list[Alignment] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)
    ledger_record_ids: list[str] = Field(default_factory=list)
    trust_profile: TrustProfile | None = None
    experience_graph: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    artifacts_note: str = (
        "EVE artifacts are memory/context for the next seed/run, never weight updates."
    )
    engines: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = (
        "SIMULATED. Synthetic statistical personas, not real people. "
        "Outputs are scenario projections under stated assumptions, never 'the future is'."
    )
    t0_event_ids: list[str] = Field(default_factory=list)
    t1_event_n: int = 0


class ClosedLoop:
    def __init__(
        self,
        *,
        ledger: RealityLedger | None = None,
        graph: ExperienceGraph | None = None,
        aligner: RealityAligner | None = None,
        adapter: MiroWorldAdapter | None = None,
    ) -> None:
        self.ledger = ledger or RealityLedger()
        self.graph = graph or ExperienceGraph()
        self.aligner = aligner or RealityAligner()
        self.adapter = adapter or MiroWorldAdapter()
        self.artifacts: list[dict[str, Any]] = []

    async def run(
        self,
        experiment: ExperimentSpec | str | Path,
        store: EventStore,
        t0_events: list[WorldEvent],
        t1_events: list[WorldEvent],
        *,
        agents: int | None = None,
        seeds: list[int] | None = None,
        horizon_hours: int | float | str | None = None,
        world_id: str | None = None,
    ) -> ClosedLoopResult:
        spec = experiment if isinstance(experiment, ExperimentSpec) else load_experiment(experiment)
        cutoff = spec.cutoff
        hours = parse_horizon(horizon_hours, default=spec.horizon_hours)
        n_agents = int(agents if agents is not None else spec.agents)
        seed_list = list(seeds if seeds is not None else spec.seeds)
        wid = world_id or f"world_{spec.id}_{uuid4().hex[:8]}"

        observed_t0 = [e for e in t0_events if e.kind == ProvenanceKind.OBSERVED]
        forecast_t0 = [e for e in t0_events if e.kind == ProvenanceKind.FORECAST]
        # WorldState(t0) from OBSERVED only; reject post-cutoff leaks.
        world_t0 = project_world_state(
            wid,
            observed_t0,
            at=cutoff,
            information_cutoff=cutoff,
            reject_leaks=True,
            synthetic_population=n_agents,
        )
        store.append_many(
            wid, observed_t0, channel=ProvenanceKind.OBSERVED, information_cutoff=cutoff
        )

        input_kinds = sorted({e.kind.value for e in observed_t0 + forecast_t0})
        source_versions: dict[str, str] = {}
        source_providers: list[str] = []
        for e in observed_t0 + forecast_t0:
            key = e.source.provider
            source_versions[key] = e.source.version or e.source.dataset
            if e.source.provider not in source_providers:
                source_providers.append(e.source.provider)

        provenance_for_tag = [k for k in input_kinds if k in {"observed", "forecast"}]
        if not provenance_for_tag:
            provenance_for_tag = ["observed"]

        seed_runs: list[SeedRun] = []
        engine_notes: dict[str, Any] = {}

        for sc_spec in spec.scenarios:
            interventions: list[Intervention] = []
            raw_iv = sc_spec.intervention
            if raw_iv:
                lead = int(raw_iv.get("lead_time_minutes") or 0)
                interventions.append(
                    Intervention(
                        type=str(raw_iv.get("type") or "evacuation_warning"),
                        timestamp=intervention_timestamp(lead, hours),
                        coverage=float(raw_iv.get("coverage") or 0.8),
                    )
                )
            for seed in seed_list:
                scenario = Scenario(
                    name=f"{spec.id}:{sc_spec.id}",
                    type="typhoon",
                    initial_world={"timestamp": iso(cutoff)},
                    duration={"simulated_hours": hours},
                    agents={"population": n_agents},
                    interventions=interventions,
                    random_seed=int(seed),
                    information_cutoff=iso(cutoff),
                )
                sim_engine = get_simulation_engine(scenario, artifacts=list(self.artifacts))
                pop = Population(synthetic_n=n_agents)
                sim = await sim_engine.initialize(world_t0, pop)
                sim.id = f"sim_{wid}_{sc_spec.id}_{seed}"
                miro_seed = self.adapter.adapt(world_t0, sim.personas, events=observed_t0 + forecast_t0)
                sim.world_snapshot = miro_seed.to_snapshot()
                until = sim.origin + timedelta(hours=hours)
                result = await sim_engine.run(sim, until)
                notes = getattr(sim_engine, "last_notes", None)
                engine_notes["simulation"] = getattr(sim_engine, "name", type(sim_engine).__name__)
                engine_notes["simulation_notes"] = notes

                observations = perceive_population(
                    sim.personas, world_t0, observed_t0, t=world_t0.timestamp
                )
                trajectories = agent_trajectories_from_result(
                    result,
                    observations=observations,
                    scenario_id=sc_spec.id,
                    seed=seed,
                )
                exp_engine = get_experience_engine()
                engine_notes["experience"] = getattr(exp_engine, "name", type(exp_engine).__name__)
                validated = await observe_and_validate(
                    exp_engine,
                    trajectories,
                    predicted_series=result.predicted_series,
                    world_state_timestamp=iso(world_t0.timestamp),
                    event_ids=list(world_t0.events),
                    source_providers=source_providers,
                    simulation_id=sim.id,
                    validate=bool(spec.experiment.experience.should_validate),
                    episode_id=f"{spec.id}:{sc_spec.id}:seed{seed}",
                )
                engine_notes["experience_notes"] = getattr(exp_engine, "last_notes", None)

                for val in validated:
                    fp = fingerprint_of(val.layer, val.artifact)
                    self.graph.add_candidate(
                        val.id,
                        layer=val.layer,
                        fingerprint=fp,
                        artifact=val.artifact,
                    )
                    self.graph.mark_validated(val.id)
                    if val.artifact:
                        # memory/context for the next seed/run — never a weight update
                        self.artifacts.append(dict(val.artifact))

                evac_n = float((result.summary or {}).get("evacuated") or 0)
                peak_wind = float((result.summary or {}).get("peak_wind") or 0)
                peak_cong = float((result.summary or {}).get("peak_congestion") or 0)
                pop_n = max(float(sim.population_n or n_agents), 1.0)
                seed_runs.append(
                    SeedRun(
                        scenario_id=sc_spec.id,
                        seed=int(seed),
                        simulation_id=sim.id,
                        summary=dict(result.summary or {}),
                        predicted_series={k: list(v) for k, v in (result.predicted_series or {}).items()},
                        predicted_times=list(result.predicted_times or []),
                        evacuation_rate=evac_n / pop_n,
                        peak_wind=peak_wind,
                        peak_congestion=peak_cong,
                        experience_ids=[v.id for v in validated],
                        engine_notes=notes,
                    )
                )

        aggregates: dict[str, ScenarioAggregate] = {}
        for sc_spec in spec.scenarios:
            runs = [r for r in seed_runs if r.scenario_id == sc_spec.id]
            winds = [r.predicted_series.get("wind_speed_10m") or [] for r in runs]
            mean_wind = mean_series(winds)
            times = next((r.predicted_times for r in runs if r.predicted_times), [])
            mean_cong = mean_series([r.predicted_series.get("congestion") or [] for r in runs])
            mean_series_map = {"wind_speed_10m": mean_wind}
            if mean_cong:
                mean_series_map["congestion"] = mean_cong
            aggregates[sc_spec.id] = ScenarioAggregate(
                scenario_id=sc_spec.id,
                n_seeds=len(runs),
                evacuation_rate=summarize_scalar([r.evacuation_rate for r in runs]),
                peak_wind=summarize_scalar([r.peak_wind for r in runs]),
                peak_congestion=summarize_scalar([r.peak_congestion for r in runs]),
                wind_speed_10m={
                    "mean": mean_wind,
                    "variance": variance_series(winds),
                },
                mean_predicted_series=mean_series_map,
                mean_predicted_times=list(times)[: len(mean_wind)] if mean_wind else list(times),
            )

        t1_world = None
        if t1_events:
            t1_at = max(as_utc(e.temporal.effective_time) for e in t1_events)
            t1_world = project_world_state(
                f"{wid}_t1",
                t1_events,
                at=t1_at,
                information_cutoff=t1_at,
                reject_leaks=False,
            )

        alignments: list[Alignment] = []
        evaluations: list[dict[str, Any]] = []
        ledger_ids: list[str] = []
        centroid = world_t0.geography.centroid
        metrics = list(spec.experiment.evaluation.metrics)

        for sc_id, agg in aggregates.items():
            aligned = self.aligner.align(
                predicted_series=agg.mean_predicted_series,
                predicted_times=agg.mean_predicted_times,
                t1_events=t1_events,
                t1_world=t1_world,
                input_provenance_kinds=provenance_for_tag,
                pred_coords=(centroid[0], centroid[1]),
                metrics=metrics,
            )
            alignments.extend(aligned)
            for al in aligned:
                rec = self.ledger.record_prediction(
                    experiment_id=spec.id,
                    scenario_id=sc_id,
                    model=str(engine_notes.get("simulation") or "mirofish"),
                    seed=None,  # distribution over seeds, not a single run
                    cutoff=cutoff,
                    source_versions=source_versions,
                    input_provenance_kinds=list(al.input_provenance_kinds or provenance_for_tag),
                    domain=_domain_for_metric(al.metric_name),
                    predicted=al.predicted,
                    observed=al.observed,
                    times=al.times,
                    notes="evaluated on seed distribution mean, not a single seed",
                )
                ledger_ids.append(rec.id)
                if al.mae is not None:
                    evaluations.append(
                        {
                            "scenario_id": sc_id,
                            "metric_name": al.metric_name,
                            "mae": al.mae,
                            "brier": al.brier,
                            "calibration": al.calibration,
                            "spatial_error_km": al.spatial_error_km,
                            "temporal_error_minutes": al.temporal_error_minutes,
                            "n_seeds": agg.n_seeds,
                            "verdict": rec.verdict,
                        }
                    )
                    for node in self.graph.nodes():
                        if node.layer == "simulator_vs_reality":
                            self.graph.maybe_conflict_on_mae(node.id, al.mae)

        # Ensure every listed domain has a ledger presence (empty → DO_NOT_USE).
        present_domains = {getattr(r, "domain", "") for r in self.ledger.for_experiment(spec.id)}
        for domain in ("weather", "mobility", "population", "news"):
            if domain in present_domains:
                continue
            rec = self.ledger.record_prediction(
                experiment_id=spec.id,
                scenario_id="*",
                model=str(engine_notes.get("simulation") or "mirofish"),
                cutoff=cutoff,
                source_versions=source_versions,
                input_provenance_kinds=provenance_for_tag,
                domain=domain,
                predicted=[],
                observed=[],
                notes="no aligned observations for this domain",
            )
            ledger_ids.append(rec.id)

        profile = trust_profile_from_ledger(
            self.ledger.for_experiment(spec.id), experiment_id=spec.id
        )
        return ClosedLoopResult(
            experiment_id=spec.id,
            world_id=wid,
            information_cutoff=cutoff,
            t0_timestamp=world_t0.timestamp,
            seed_runs=seed_runs,
            aggregates=aggregates,
            alignments=alignments,
            evaluations=evaluations,
            ledger_record_ids=ledger_ids,
            trust_profile=profile,
            experience_graph=self.graph.summary(),
            artifacts=list(self.artifacts),
            engines=engine_notes,
            t0_event_ids=list(world_t0.events),
            t1_event_n=len(t1_events),
        )


def _domain_for_metric(name: str) -> str:
    if name.startswith("wind") or name.startswith("precip") or name == "temperature_2m":
        return "weather"
    if name in {"congestion", "evacuation_rate"}:
        return "mobility"
    if name in {"population", "stuck"}:
        return "population"
    if name.startswith("news"):
        return "news"
    return "weather"


def default_store() -> EventStore:
    return InMemoryEventStore()
