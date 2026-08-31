"""SimulationEngine protocol. In-tree MiroFish is behind this interface.

When ``EVE_MIRO_ENGINES=stub`` (pytest) the factory returns ``StubSimulationEngine``.
Otherwise (default ``in-tree``) it returns ``MiroFishEngine``, which raises
``EngineNotConfigured`` instead of silently stubbing.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from eve_miro.core.simulation.population import Persona, generate_population, population_summary
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState
from eve_miro.core.world.temporal import as_utc, iso, parse_offset, utcnow


class AgentAction(BaseModel):
    agent_id: str
    t: datetime
    hour: int
    action: Literal["stay", "evacuate", "shelter", "stuck", "buy", "sell", "hold"]
    wind_speed: float
    congestion: float
    warning_active: bool
    warning_received: bool
    outcome: str
    provenance_kind: ProvenanceKind = ProvenanceKind.SIMULATED


class SimulationStep(BaseModel):
    hour: int
    t: datetime
    wind_speed: float
    precipitation: float
    congestion: float
    warning_active: bool
    evacuated_n: int
    stuck_n: int
    actions: list[AgentAction] = Field(default_factory=list)
    price: float | None = None


class Simulation(BaseModel):
    id: str
    world_id: str
    scenario_name: str
    status: Literal["created", "running", "paused", "completed"] = "created"
    information_cutoff: datetime
    origin: datetime
    hours: int
    seed: int
    population_n: int
    personas: list[Persona] = Field(default_factory=list)
    steps: list[SimulationStep] = Field(default_factory=list)
    interventions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    cursor_hour: int = 0
    provenance_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    scenario_type: str = "typhoon"
    world_snapshot: dict[str, Any] = Field(default_factory=dict)
    learning_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = (
        "SIMULATED. Synthetic statistical personas, not real people. "
        "Outputs are scenario projections under stated assumptions, never 'the future is'."
    )


class SimulationResult(BaseModel):
    simulation: Simulation
    traces: list[dict[str, Any]] = Field(default_factory=list)
    predicted_series: dict[str, list[float]] = Field(default_factory=dict)
    predicted_times: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SimulationEngine(Protocol):
    async def initialize(self, world: WorldState, population: Population) -> Simulation: ...

    async def step(self, simulation: Simulation) -> SimulationStep: ...

    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult: ...


def _env(name: str) -> str | None:
    import os

    v = os.environ.get(name, "").strip()
    return v or None


def get_simulation_engine(
    scenario: Scenario | None = None,
    *,
    artifacts: list[dict[str, Any]] | None = None,
) -> SimulationEngine:
    """Stub only when ``EVE_MIRO_ENGINES=stub``. Otherwise fail closed."""
    from eve_miro.core.simulation.mirofish_adapter import MiroFishEngine
    from eve_miro.paths import engines_mode

    if engines_mode() == "stub":
        return StubSimulationEngine(scenario=scenario, artifacts=artifacts)
    return MiroFishEngine(scenario=scenario, artifacts=artifacts)


def is_warning_delay_artifact(artifact: dict[str, Any]) -> bool:
    """True when a learning artifact about late warnings has confidence > 0.8."""
    if float(artifact.get("confidence") or 0) <= 0.8:
        return False
    blob = " ".join(
        [
            str(artifact.get("experience") or ""),
            " ".join(str(c) for c in (artifact.get("conditions") or [])),
        ]
    ).lower()
    return "warning" in blob and ("delay" in blob or "late" in blob or "after congestion" in blob)


def typhoon_wind(hour: float, *, peak_hour: float = 36.0, peak: float = 110.0, base: float = 18.0) -> float:
    return base + peak * math.exp(-((hour - peak_hour) ** 2) / (2 * 12.0 ** 2))


def typhoon_precip(hour: float, wind: float) -> float:
    return max(0.0, (wind - 20.0) / 8.0 + 2.0 * math.sin(hour / 6.0))


class StubSimulationEngine:
    """Tiny Philippines typhoon-style run. Replaceable: this is not MiroFish."""

    name = "stub"

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        self.scenario = scenario
        self.artifacts = list(artifacts or [])

    def _scenario_type(self) -> str:
        sc = self.scenario
        if sc is not None and getattr(sc, "type", None):
            return str(sc.type)
        return "typhoon"

    def _is_market(self, simulation: Simulation | None = None) -> bool:
        if simulation is not None:
            return simulation.scenario_type == "market"
        return self._scenario_type() == "market"

    def _reduce_cascade(self, simulation: Simulation) -> bool:
        for art in list(simulation.learning_artifacts) + list(self.artifacts):
            if is_warning_delay_artifact(art):
                return True
        return False

    async def initialize(self, world: WorldState, population: Population) -> Simulation:
        sc = self.scenario
        n = population.synthetic_n or (sc.population if sc else 200)
        seed = sc.random_seed if sc else 48291
        rng = random.Random(seed)
        origin = sc.origin if sc else world.timestamp
        hours = sc.simulated_hours if sc else 24
        cutoff = sc.cutoff if sc else world.information_cutoff
        stype = self._scenario_type()
        role = "investor" if stype == "market" else "civilian"
        personas = generate_population(n, rng, role=role)
        interventions = [i.model_dump() for i in (sc.interventions if sc else [])]
        disclaimer = (
            sc.disclaimer
            if sc is not None and getattr(sc, "disclaimer", None)
            else (
                "SIMULATED. Synthetic statistical personas, not real people. "
                "Outputs are scenario projections under stated assumptions, never 'the future is'."
            )
        )
        return Simulation(
            id=f"sim_{world.world_id}_{seed}",
            world_id=world.world_id,
            scenario_name=sc.name if sc else "ad_hoc",
            status="created",
            information_cutoff=cutoff,
            origin=origin,
            hours=hours,
            seed=seed,
            population_n=n,
            personas=personas,
            interventions=interventions,
            scenario_type=stype,
            world_snapshot={
                "economy": world.economy.model_dump() if world.economy else {},
                "timestamp": world.timestamp.isoformat(),
            },
            learning_artifacts=list(self.artifacts),
            disclaimer=disclaimer,
        )

    def _warning_hour(self, simulation: Simulation) -> int | None:
        for raw in simulation.interventions:
            if raw.get("type") == "evacuation_warning":
                t = parse_offset(str(raw["timestamp"]), simulation.origin)
                return int((t - simulation.origin).total_seconds() // 3600)
        return None

    def _coverage(self, simulation: Simulation) -> float:
        for raw in simulation.interventions:
            if raw.get("type") == "evacuation_warning":
                return float(raw.get("coverage", 0.8))
        return 0.0

    async def step(self, simulation: Simulation) -> SimulationStep:
        if self._is_market(simulation):
            return await self._step_market(simulation)
        hour = simulation.cursor_hour
        t = simulation.origin + timedelta(hours=hour)
        rng = random.Random(simulation.seed + hour * 997)
        wind = typhoon_wind(hour)
        precip = typhoon_precip(hour, wind)
        warn_h = self._warning_hour(simulation)
        coverage = self._coverage(simulation)
        warning_active = warn_h is not None and hour >= warn_h
        reduce_cascade = self._reduce_cascade(simulation)

        # Early self-evacuation as wind rises creates congestion BEFORE a late warning.
        prior_on_road = 0
        if simulation.steps:
            prior_on_road = simulation.steps[-1].evacuated_n
        base_congestion = min(1.0, prior_on_road / max(simulation.population_n * 0.25, 1))
        # congestion grows if people already moving
        congestion = min(1.0, 0.05 + 0.7 * base_congestion + 0.002 * max(0.0, wind - 40))
        if reduce_cascade:
            # Learned rule: high-confidence warning-delay artifact → reduce cascade.
            congestion *= 0.4

        actions: list[AgentAction] = []
        evacuated = 0
        stuck = 0
        sheltered = 0
        already = {a.agent_id for step in simulation.steps for a in step.actions if a.action in {"evacuate", "shelter", "stuck"}}

        for p in simulation.personas:
            if p.agent_id in already:
                continue
            received = warning_active and (rng.random() < coverage) and (p.risk_aversion > 0.15)
            # Self-evacuate when wind is high even without warning (creates pre-warning congestion).
            self_ev = (not warning_active) and wind >= 35 and p.risk_aversion > 0.72 and p.vehicle_access
            want = received or self_ev or (warning_active and p.risk_aversion > 0.85 and wind > 50)
            if want:
                # Late warning after congestion is ineffective.
                delay_bad = warning_active and congestion > 0.35 and (warn_h is not None and hour - warn_h <= 2)
                jammed = congestion > 0.45 and (self_ev is False) and (delay_bad or not p.vehicle_access)
                if jammed and reduce_cascade and rng.random() < 0.75:
                    act: str = "evacuate"
                    evacuated += 1
                    outcome = "evacuated"
                elif jammed:
                    act = "stuck"
                    stuck += 1
                    outcome = "congestion_blocked"
                elif p.shelter_access and wind > 80:
                    act = "shelter"
                    sheltered += 1
                    outcome = "sheltered"
                else:
                    act = "evacuate"
                    evacuated += 1
                    outcome = "evacuated"
            else:
                act = "stay"
                outcome = "remained"
            actions.append(
                AgentAction(
                    agent_id=p.agent_id,
                    t=t,
                    hour=hour,
                    action=act,  # type: ignore[arg-type]
                    wind_speed=round(wind, 2),
                    congestion=round(congestion, 3),
                    warning_active=warning_active,
                    warning_received=received,
                    outcome=outcome,
                )
            )

        # Update congestion after this hour's departures
        congestion = min(1.0, congestion + evacuated / max(simulation.population_n, 1) * 2.2)
        step = SimulationStep(
            hour=hour,
            t=t,
            wind_speed=round(wind, 2),
            precipitation=round(max(0.0, precip), 2),
            congestion=round(congestion, 3),
            warning_active=warning_active,
            evacuated_n=evacuated,
            stuck_n=stuck,
            actions=actions,
        )
        simulation.steps.append(step)
        simulation.cursor_hour += 1
        return step

    async def _step_market(self, simulation: Simulation) -> SimulationStep:
        """Tiny investor-population reaction to ingested CoinGecko-like prices. SIMULATED."""
        hour = simulation.cursor_hour
        t = simulation.origin + timedelta(hours=hour)
        rng = random.Random(simulation.seed + hour * 997)
        market = ((simulation.world_snapshot or {}).get("economy") or {}).get("indicators") or {}
        market = market.get("market") or {}
        latest = market.get("latest") or {}
        base_price = float(latest.get("price") or 100.0)
        prev = simulation.steps[-1].price if simulation.steps and simulation.steps[-1].price is not None else base_price
        # Subsequent prices are SIMULATED (seeded random walk). Initial base is OBSERVED context only.
        price = max(0.01, prev * (1.0 + rng.uniform(-0.03, 0.03)))
        change = (price - prev) / prev if prev else 0.0
        actions: list[AgentAction] = []
        buy = sell = hold = 0
        for p in simulation.personas:
            if change < -0.01 and p.risk_aversion > 0.5:
                act: str = "sell"
                sell += 1
                outcome = "sold"
            elif change > 0.01 and p.risk_aversion < 0.5:
                act = "buy"
                buy += 1
                outcome = "bought"
            else:
                act = "hold"
                hold += 1
                outcome = "held"
            actions.append(
                AgentAction(
                    agent_id=p.agent_id,
                    t=t,
                    hour=hour,
                    action=act,  # type: ignore[arg-type]
                    wind_speed=0.0,
                    congestion=0.0,
                    warning_active=False,
                    warning_received=False,
                    outcome=outcome,
                    provenance_kind=ProvenanceKind.SIMULATED,
                )
            )
        step = SimulationStep(
            hour=hour,
            t=t,
            wind_speed=0.0,
            precipitation=0.0,
            congestion=0.0,
            warning_active=False,
            evacuated_n=buy,
            stuck_n=sell,
            actions=actions,
            price=round(price, 4),
        )
        simulation.steps.append(step)
        simulation.cursor_hour += 1
        return step

    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult:
        simulation.status = "running"
        until = as_utc(until)
        max_hours = simulation.hours
        while simulation.cursor_hour < max_hours:
            t = simulation.origin + timedelta(hours=simulation.cursor_hour)
            if t > until:
                break
            await self.step(simulation)
        simulation.status = "completed" if simulation.cursor_hour >= max_hours else "paused"
        if self._is_market(simulation):
            return self._market_result(simulation)
        traces: list[dict[str, Any]] = []
        winds: list[float] = []
        times: list[str] = []
        for st in simulation.steps:
            winds.append(st.wind_speed)
            times.append(iso(st.t))
            for a in st.actions:
                traces.append(
                    {
                        "simulation_id": simulation.id,
                        "hour": a.hour,
                        "t": iso(a.t),
                        "agent_id": a.agent_id,
                        "action": a.action,
                        "wind_speed": a.wind_speed,
                        "congestion": a.congestion,
                        "warning_active": a.warning_active,
                        "outcome": a.outcome,
                        "provenance_kind": a.provenance_kind.value,
                    }
                )
        summary = {
            "hours": len(simulation.steps),
            "evacuated": sum(s.evacuated_n for s in simulation.steps),
            "stuck": sum(s.stuck_n for s in simulation.steps),
            "peak_wind": max(winds) if winds else 0,
            "peak_congestion": max((s.congestion for s in simulation.steps), default=0),
            "population": population_summary(simulation.personas),
            "provenance_kind": ProvenanceKind.SIMULATED.value,
            "disclaimer": simulation.disclaimer,
            "cascade_reduced": self._reduce_cascade(simulation),
        }
        return SimulationResult(
            simulation=simulation,
            traces=traces,
            predicted_series={"wind_speed_10m": winds, "congestion": [s.congestion for s in simulation.steps]},
            predicted_times=times,
            summary=summary,
        )

    def _market_result(self, simulation: Simulation) -> SimulationResult:
        traces: list[dict[str, Any]] = []
        prices: list[float] = []
        times: list[str] = []
        buy = sell = hold = 0
        for st in simulation.steps:
            if st.price is not None:
                prices.append(st.price)
            times.append(iso(st.t))
            for a in st.actions:
                if a.action == "buy":
                    buy += 1
                elif a.action == "sell":
                    sell += 1
                else:
                    hold += 1
                traces.append(
                    {
                        "simulation_id": simulation.id,
                        "hour": a.hour,
                        "t": iso(a.t),
                        "agent_id": a.agent_id,
                        "action": a.action,
                        "outcome": a.outcome,
                        "price": st.price,
                        "provenance_kind": a.provenance_kind.value,
                    }
                )
        summary = {
            "hours": len(simulation.steps),
            "buy": buy,
            "sell": sell,
            "hold": hold,
            "peak_price": max(prices) if prices else 0,
            "population": population_summary(simulation.personas),
            "provenance_kind": ProvenanceKind.SIMULATED.value,
            "disclaimer": simulation.disclaimer,
            "scenario_type": "market",
        }
        return SimulationResult(
            simulation=simulation,
            traces=traces,
            predicted_series={"price": prices},
            predicted_times=times,
            summary=summary,
        )
