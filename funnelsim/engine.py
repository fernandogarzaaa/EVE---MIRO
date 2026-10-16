"""FunnelSimEngine: agent-based funnel simulator behind SimulationEngine.

Simulates the Moovloop post-job SMS loop (jobs -> texts -> reviews /
problems / opt-outs) and, in speed-to-lead mode, pre-job lead response ->
booking conversion. Produces SIMULATED scenario-conditioned outcome
distributions: reviews per 100 jobs, problems routed, cost, revenue,
opt-out rate.

This engine never stubs: without a funnel scenario it raises
``EngineNotConfigured`` (fail closed). All outputs are SIMULATED; only the
baseline parameters come from OBSERVED fixture context (proposal figures
with provenance in datasets/fixtures/funnel_baseline.json).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from eve_miro.core.simulation.engine import (
    AgentAction,
    Simulation,
    SimulationResult,
    SimulationStep,
)
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.state import Population, WorldState
from eve_miro.core.world.temporal import as_utc, iso
from eve_miro.errors import EngineNotConfigured
from funnelsim.agents import CustomerAgent, CustomerState, MoverOfficeAgent, SpeedLead
from funnelsim.economics import Pricing, loop_variable_cost, monthly_fixed_cost

FUNNEL_DISCLAIMER = (
    "SIMULATED. Scenario projection under stated assumptions, not a forecast. "
    "Customer agents are synthetic statistical personas, not real people. "
    "Baseline parameters are observed proposal/fixture context; every outcome "
    "after t0 is simulated."
)

POST_JOB = "post_job"
SPEED_TO_LEAD = "speed_to_lead"
MODES = (POST_JOB, SPEED_TO_LEAD)


def _intervention_day(raw: dict[str, Any]) -> int | None:
    """Parse intervention timestamps '+Nd' / '+Nh' into a day index.

    Returns None (caller skips) on unparseable timestamps: fail closed,
    never silently mis-time an intervention.
    """
    ts = str(raw.get("timestamp", "")).strip()
    if ts.startswith("+") and len(ts) > 2:
        try:
            if ts.endswith("d"):
                return int(ts[1:-1])
            if ts.endswith("h"):
                return int(ts[1:-1]) // 24
        except ValueError:
            return None
    return None


def _positive_float(value: Any, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineNotConfigured(f"funnelsim: {name} must be a number, got {value!r}") from exc
    if v < 0:
        raise EngineNotConfigured(f"funnelsim: {name} must be non-negative, got {v}")
    return v


@dataclass
class _FunnelParams:
    mode: str = POST_JOB
    jobs_per_month: float = 60.0
    contactable_coverage: float = 0.80
    review_conversion: float = 0.20
    opt_out_rate: float = 0.01
    problem_rate: float = 0.20
    problem_resolve_prob: float = 0.70
    office_response_days_mean: float = 2.0
    leads_per_day: float = 10.0
    response_mean_covered_min: float = 1.0
    response_mean_uncovered_min: float = 8.0
    book_prob_fast: float = 0.55
    book_prob_slow: float = 0.15
    pricing: Pricing = field(default_factory=Pricing)


@dataclass
class _ActiveWindows:
    opt_out_multiplier: float = 1.0
    opt_out_until_day: int = -1
    review_cap_per_day: float = math.inf  # set via google_enforcement
    review_cap_until_day: int = -1
    office_slowdown_mult: float = 1.0
    office_slowdown_until_day: int = -1


@dataclass
class _DayTotals:
    jobs: int = 0
    contacted: int = 0
    texts: int = 0
    reviews: int = 0
    reviews_flagged: int = 0
    problems_routed: int = 0
    problems_resolved: int = 0
    opt_outs: int = 0
    leads: int = 0
    bookings: int = 0


@dataclass
class _FunnelState:
    params: _FunnelParams
    offices: dict[str, MoverOfficeAgent]
    customers: dict[str, CustomerAgent] = field(default_factory=dict)
    windows: _ActiveWindows = field(default_factory=_ActiveWindows)
    rng: random.Random = field(default_factory=random.Random)
    day: int = 0
    reviews_today: int = 0
    cum: _DayTotals = field(default_factory=_DayTotals)
    daily: list[_DayTotals] = field(default_factory=list)
    cost_cum: float = 0.0
    revenue_cum: float = 0.0
    cost_series: list[float] = field(default_factory=list)
    revenue_series: list[float] = field(default_factory=list)


class FunnelSimEngine:
    """SimulationEngine for Moovloop funnel scenarios. Pure Python, no keys."""

    name = "funnelsim"

    def __init__(
        self,
        scenario: Scenario | None = None,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.scenario = scenario
        self.artifacts = list(artifacts or [])
        self._states: dict[str, _FunnelState] = {}

    # -- initialize ------------------------------------------------------
    def _params_from(self, sc: Scenario) -> _FunnelParams:
        c = dict(sc.conditions or {})
        mode = str(c.get("mode", POST_JOB))
        if mode not in MODES:
            raise EngineNotConfigured(f"funnelsim: unknown mode {mode!r} (expected one of {MODES})")
        p = _FunnelParams(mode=mode)
        if mode == POST_JOB:
            if "jobs_per_month" not in c:
                raise EngineNotConfigured("funnelsim: post_job mode requires conditions.jobs_per_month")
            p.jobs_per_month = _positive_float(c["jobs_per_month"], "jobs_per_month")
            if p.jobs_per_month <= 0:
                raise EngineNotConfigured("funnelsim: jobs_per_month must be positive")
            p.contactable_coverage = _positive_float(
                c.get("contactable_coverage", 0.80), "contactable_coverage"
            )
            p.review_conversion = _positive_float(c.get("review_conversion", 0.20), "review_conversion")
            p.opt_out_rate = _positive_float(c.get("opt_out_rate", 0.01), "opt_out_rate")
            p.problem_rate = _positive_float(c.get("problem_rate", 0.20), "problem_rate")
            p.problem_resolve_prob = _positive_float(
                c.get("problem_resolve_prob", 0.70), "problem_resolve_prob"
            )
            p.office_response_days_mean = _positive_float(
                c.get("office_response_days_mean", 2.0), "office_response_days_mean"
            )
            for prob_name, prob in (
                ("contactable_coverage", p.contactable_coverage),
                ("review_conversion", p.review_conversion),
                ("opt_out_rate", p.opt_out_rate),
                ("problem_rate", p.problem_rate),
                ("problem_resolve_prob", p.problem_resolve_prob),
            ):
                if prob > 1.0:
                    raise EngineNotConfigured(f"funnelsim: {prob_name} must be <= 1, got {prob}")
            if p.opt_out_rate + p.problem_rate + p.review_conversion > 1.0:
                raise EngineNotConfigured(
                    "funnelsim: opt_out_rate + problem_rate + review_conversion must be <= 1, "
                    f"got {p.opt_out_rate + p.problem_rate + p.review_conversion}"
                )
        else:
            p.leads_per_day = _positive_float(c.get("leads_per_day", 10.0), "leads_per_day")
            if p.leads_per_day <= 0:
                raise EngineNotConfigured("funnelsim: leads_per_day must be positive")
            p.contactable_coverage = _positive_float(
                c.get("contactable_coverage", 0.80), "contactable_coverage"
            )
            p.response_mean_covered_min = _positive_float(
                c.get("response_mean_covered_min", 1.0), "response_mean_covered_min"
            )
            p.response_mean_uncovered_min = _positive_float(
                c.get("response_mean_uncovered_min", 8.0), "response_mean_uncovered_min"
            )
            p.book_prob_fast = _positive_float(c.get("book_prob_fast", 0.55), "book_prob_fast")
            p.book_prob_slow = _positive_float(c.get("book_prob_slow", 0.15), "book_prob_slow")
        pricing = c.get("pricing") or {}
        if not isinstance(pricing, dict):
            raise EngineNotConfigured("funnelsim: conditions.pricing must be a mapping")
        p.pricing = Pricing(
            per_job=_positive_float(pricing.get("per_job", 0.80), "pricing.per_job"),
            per_review_bonus=_positive_float(
                pricing.get("per_review_bonus", 5.00), "pricing.per_review_bonus"
            ),
            per_problem_bonus=_positive_float(
                pricing.get("per_problem_bonus", 10.00), "pricing.per_problem_bonus"
            ),
            per_booking_bonus=_positive_float(
                pricing.get("per_booking_bonus", 25.00), "pricing.per_booking_bonus"
            ),
            text_cost=_positive_float(pricing.get("text_cost", 0.013), "pricing.text_cost"),
            dlc_setup=_positive_float(pricing.get("dlc_setup", 19.50), "pricing.dlc_setup"),
            dlc_monthly_fee=_positive_float(pricing.get("dlc_monthly_fee", 2.00), "pricing.dlc_monthly_fee"),
        )
        return p

    async def initialize(self, world: WorldState, population: Population) -> Simulation:
        sc = self.scenario
        if sc is None:
            raise EngineNotConfigured("funnelsim: no scenario: refusing to invent funnel parameters")
        params = self._params_from(sc)
        seed = sc.random_seed
        origin = sc.origin
        days = int((sc.conditions or {}).get("simulated_days", 0)) or max(sc.simulated_hours // 24, 1)
        cutoff = sc.cutoff

        n_movers = population.synthetic_n or sc.population or 3
        rng = random.Random(seed)
        offices: dict[str, MoverOfficeAgent] = {}
        for m in range(n_movers):
            mover_id = f"mover-{m:02d}"
            offices[mover_id] = MoverOfficeAgent(
                mover_id=mover_id,
                response_days_mean=params.office_response_days_mean,
                resolve_prob=params.problem_resolve_prob,
                rng=random.Random(seed + 7919 + m * 131),
            )

        sim_id = f"funnelsim_{world.world_id}_{seed}"
        self._states[sim_id] = _FunnelState(params=params, offices=offices, rng=rng)

        disclaimer = sc.disclaimer if getattr(sc, "disclaimer", None) else FUNNEL_DISCLAIMER
        return Simulation(
            id=sim_id,
            world_id=world.world_id,
            scenario_name=sc.name,
            status="created",
            information_cutoff=cutoff,
            origin=origin,
            hours=days * 24,
            seed=seed,
            population_n=n_movers,
            personas=[],
            interventions=[i.model_dump() for i in sc.interventions],
            scenario_type="funnel",
            world_snapshot={
                "mode": params.mode,
                "n_movers": n_movers,
                "note": "OBSERVED baseline parameters from fixture; all outcomes SIMULATED.",
                "timestamp": world.timestamp.isoformat(),
            },
            learning_artifacts=list(self.artifacts),
            disclaimer=disclaimer,
        )

    # -- stepping ----------------------------------------------------------
    def _state(self, simulation: Simulation) -> _FunnelState:
        try:
            return self._states[simulation.id]
        except KeyError as exc:
            raise EngineNotConfigured(
                f"funnelsim: no state for simulation {simulation.id}; initialize first"
            ) from exc

    def _apply_interventions(self, simulation: Simulation, state: _FunnelState, day: int) -> None:
        w = state.windows
        for raw in simulation.interventions:
            if _intervention_day(raw) != day:
                continue
            itype = str(raw.get("type", ""))
            extra = dict(raw.get("extra") or {})
            if itype == "carrier_crackdown":
                w.opt_out_multiplier = float(extra.get("opt_out_multiplier", 5.0))
                w.opt_out_until_day = day + int(extra.get("duration_days", 14))
            elif itype == "google_enforcement":
                w.review_cap_per_day = float(extra.get("max_reviews_per_day", 3.0))
                w.review_cap_until_day = day + int(extra.get("duration_days", 10**9))
            elif itype == "office_slowdown":
                w.office_slowdown_mult = float(extra.get("response_time_multiplier", 3.0))
                w.office_slowdown_until_day = day + int(extra.get("duration_days", 30))
                for office in state.offices.values():
                    office.response_days_mean = (
                        state.params.office_response_days_mean * w.office_slowdown_mult
                    )

    def _expire_windows(self, state: _FunnelState, day: int) -> None:
        w = state.windows
        if w.opt_out_until_day >= 0 and day >= w.opt_out_until_day:
            w.opt_out_multiplier = 1.0
            w.opt_out_until_day = -1
        if w.review_cap_until_day >= 0 and day >= w.review_cap_until_day:
            w.review_cap_per_day = math.inf
            w.review_cap_until_day = -1
        if w.office_slowdown_until_day >= 0 and day >= w.office_slowdown_until_day:
            w.office_slowdown_mult = 1.0
            w.office_slowdown_until_day = -1
            for office in state.offices.values():
                office.response_days_mean = state.params.office_response_days_mean

    def _arrivals(self, rate_per_day: float, rng: random.Random) -> int:
        base = int(rate_per_day)
        frac = rate_per_day - base
        return base + (1 if rng.random() < frac else 0)

    def _step_post_job(self, state: _FunnelState, day: int) -> _DayTotals:
        p = state.params
        rng = state.rng
        w = state.windows
        tot = _DayTotals()
        eff_opt_out = min(p.opt_out_rate * w.opt_out_multiplier, 1.0)

        for mover_id in sorted(state.offices):
            n_arr = self._arrivals(p.jobs_per_month / 30.0, rng)
            for _ in range(n_arr):
                cid = f"{mover_id}-c{len(state.customers):06d}"
                cust = CustomerAgent(agent_id=cid, mover_id=mover_id, rng=random.Random(rng.randrange(2**31)))
                state.customers[cid] = cust
                tot.jobs += 1
                contactable = rng.random() < p.contactable_coverage
                tot.texts += cust.contact(day, contactable=contactable)
                if contactable:
                    tot.contacted += 1

        # Nudge customers texted 3 days ago; resolve those past the nudge window.
        for cust in state.customers.values():
            if cust.state is not CustomerState.TEXTED:
                continue
            age = day - cust.day_texted
            if age == 3:
                tot.texts += cust.nudge()
            elif age >= 4:
                cust.resolve(
                    day, p_opt_out=eff_opt_out, p_problem=p.problem_rate, k_review=p.review_conversion
                )
                if cust.state is CustomerState.OPTED_OUT:
                    tot.opt_outs += 1
                elif cust.state is CustomerState.PROBLEM_REPORTED:
                    tot.problems_routed += 1
                    tot.texts += 1  # office routing text (resolve() also logs it per-customer)
                    office = state.offices[cust.mover_id]
                    resolved, _lat = office.attempt_resolve()
                    if resolved:
                        cust.state = CustomerState.PROBLEM_RESOLVED
                        cust.day_terminal = day
                        tot.problems_resolved += 1
                elif cust.state is CustomerState.REVIEWED:
                    if state.reviews_today >= w.review_cap_per_day:
                        cust.flagged = True
                        tot.reviews_flagged += 1
                    else:
                        state.reviews_today += 1
                        tot.reviews += 1
                # SILENT needs no accounting

        # Weekly owner summary text per mover (4 texts/week amortized).
        if day % 7 == 6:
            tot.texts += 4 * len(state.offices)

        return tot

    def _step_speed_to_lead(self, state: _FunnelState, day: int) -> _DayTotals:
        p = state.params
        rng = state.rng
        tot = _DayTotals()
        for mover_id in sorted(state.offices):
            n_arr = self._arrivals(p.leads_per_day, rng)
            for _ in range(n_arr):
                lid = f"{mover_id}-l{len(state.customers):06d}"
                tot.leads += 1
                covered = rng.random() < p.contactable_coverage
                mean_min = p.response_mean_covered_min if covered else p.response_mean_uncovered_min
                resp = rng.expovariate(1.0 / max(mean_min, 0.05))
                if covered:
                    tot.texts += 1  # instant SMS response
                booked = rng.random() < (p.book_prob_fast if resp <= 5.0 else p.book_prob_slow)
                lead = SpeedLead(
                    agent_id=lid, mover_id=mover_id, response_minutes=resp, booked=booked, covered=covered
                )
                state.customers[lid] = lead  # type: ignore[assignment]
                if booked:
                    tot.bookings += 1
        return tot

    async def step(self, simulation: Simulation) -> SimulationStep:
        state = self._state(simulation)
        day = state.day
        t = simulation.origin + timedelta(days=day)
        hour = day * 24
        self._apply_interventions(simulation, state, day)
        self._expire_windows(state, day)
        state.reviews_today = 0
        p = state.params

        if p.mode == POST_JOB:
            tot = self._step_post_job(state, day)
        else:
            tot = self._step_speed_to_lead(state, day)

        # Economics for the day.
        day_cost = loop_variable_cost(tot.texts, p.pricing)
        if day % 30 == 29:  # monthly fixed cost posted at month end
            day_cost += monthly_fixed_cost(p.pricing) * len(state.offices)
        if p.mode == POST_JOB:
            day_revenue = (
                tot.jobs * p.pricing.per_job
                + tot.reviews * p.pricing.per_review_bonus
                + tot.problems_resolved * p.pricing.per_problem_bonus
            )
        else:
            day_revenue = tot.bookings * p.pricing.per_booking_bonus
        state.cost_cum += day_cost
        state.revenue_cum += day_revenue
        state.cost_series.append(round(state.cost_cum, 4))
        state.revenue_series.append(round(state.revenue_cum, 4))

        # Accumulate.
        c = state.cum
        c.jobs += tot.jobs
        c.contacted += tot.contacted
        c.texts += tot.texts
        c.reviews += tot.reviews
        c.reviews_flagged += tot.reviews_flagged
        c.problems_routed += tot.problems_routed
        c.problems_resolved += tot.problems_resolved
        c.opt_outs += tot.opt_outs
        c.leads += tot.leads
        c.bookings += tot.bookings
        state.daily.append(tot)
        state.day += 1

        actions = [
            AgentAction(
                agent_id="funnel",
                t=t,
                hour=hour,
                action=f"day_close_{p.mode}",
                wind_speed=0.0,
                congestion=0.0,
                warning_active=False,
                warning_received=False,
                outcome=(
                    f"jobs={tot.jobs} reviews={tot.reviews} problems={tot.problems_routed} "
                    f"optouts={tot.opt_outs} bookings={tot.bookings}"
                ),
                provenance_kind=ProvenanceKind.SIMULATED,
            )
        ]
        step = SimulationStep(
            hour=hour,
            t=t,
            wind_speed=0.0,
            precipitation=0.0,
            congestion=0.0,
            warning_active=False,
            evacuated_n=tot.reviews,
            stuck_n=tot.opt_outs,
            actions=actions,
        )
        simulation.steps.append(step)
        simulation.cursor_hour = (day + 1) * 24
        return step

    # -- finalize ----------------------------------------------------------
    async def run(self, simulation: Simulation, until: datetime) -> SimulationResult:
        simulation.status = "running"
        until = as_utc(until)
        if simulation.id not in self._states:
            original = f"funnelsim_{simulation.world_id}_{simulation.seed}"
            if original in self._states:
                self._states[simulation.id] = self._states.pop(original)
        max_hours = simulation.hours
        while simulation.cursor_hour < max_hours:
            t = simulation.origin + timedelta(hours=simulation.cursor_hour)
            if t > until:
                break
            await self.step(simulation)
        simulation.status = "completed" if simulation.cursor_hour >= max_hours else "paused"
        return self._result(simulation)

    def _result(self, simulation: Simulation) -> SimulationResult:
        state = self._state(simulation)
        p = state.params
        c = state.cum
        days = state.day
        predicted_times = [iso(st.t) for st in simulation.steps]

        reviews_per_100: list[float] = []
        problems_routed: list[float] = []
        opt_out_rate: list[float] = []
        bookings_per_100: list[float] = []
        r_jobs = r_contacted = r_reviews = r_prob = r_opt = r_leads = r_book = 0
        for tot in state.daily:
            r_jobs += tot.jobs
            r_contacted += tot.contacted
            r_reviews += tot.reviews
            r_prob += tot.problems_routed
            r_opt += tot.opt_outs
            r_leads += tot.leads
            r_book += tot.bookings
            reviews_per_100.append(round(100.0 * r_reviews / r_jobs, 4) if r_jobs else 0.0)
            problems_routed.append(float(r_prob))
            opt_out_rate.append(round(r_opt / r_contacted, 4) if r_contacted else 0.0)
            if p.mode == SPEED_TO_LEAD:
                bookings_per_100.append(round(100.0 * r_book / r_leads, 4) if r_leads else 0.0)

        predicted_series: dict[str, list[float]] = {
            "reviews_per_100": reviews_per_100,
            "problems_routed": problems_routed,
            "cost": list(state.cost_series),
            "revenue": list(state.revenue_series),
            "opt_out_rate": opt_out_rate,
        }
        if p.mode == SPEED_TO_LEAD:
            predicted_series["bookings_per_100_leads"] = bookings_per_100

        traces: list[dict[str, Any]] = []
        for cust in state.customers.values():
            if isinstance(cust, CustomerAgent) and cust.day_terminal >= 0:
                traces.append(
                    {
                        "simulation_id": simulation.id,
                        "day": cust.day_terminal,
                        "agent_id": cust.agent_id,
                        "mover_id": cust.mover_id,
                        "action": cust.state.value,
                        "outcome": cust.state.value,
                        "texts_sent": cust.texts_sent,
                        "flagged": cust.flagged,
                        "provenance_kind": ProvenanceKind.SIMULATED.value,
                    }
                )
        margin = state.revenue_cum - state.cost_cum
        summary = {
            "days": days,
            "mode": p.mode,
            "movers": len(state.offices),
            "jobs": c.jobs,
            "contacted": c.contacted,
            "reviews_gained": c.reviews,
            "reviews_flagged": c.reviews_flagged,
            "incremental_share_pp": round(100.0 * c.reviews / c.jobs, 2) if c.jobs else 0.0,
            "implied_total_share_pp": round(18.0 + 100.0 * c.reviews / c.jobs, 2) if c.jobs else 18.0,
            "conversion": round(c.reviews / c.contacted, 4) if c.contacted else 0.0,
            "problems_routed": c.problems_routed,
            "problems_resolved": c.problems_resolved,
            "opt_outs": c.opt_outs,
            "opt_out_rate": round(c.opt_outs / c.contacted, 4) if c.contacted else 0.0,
            "leads": c.leads,
            "bookings": c.bookings,
            "cost": round(state.cost_cum, 2),
            "revenue": round(state.revenue_cum, 2),
            "margin": round(margin, 2),
            "margin_pct": round(100.0 * margin / state.revenue_cum, 1) if state.revenue_cum else 0.0,
            "provenance_kind": ProvenanceKind.SIMULATED.value,
            "disclaimer": simulation.disclaimer,
            "scenario_type": "funnel",
            "projection_only": True,
            "observed_t1": None,
            "note": "Distributions under scenarios, not forecasts. Align against pilot data when observed.",
        }
        return SimulationResult(
            simulation=simulation,
            traces=traces,
            predicted_series=predicted_series,
            predicted_times=predicted_times,
            summary=summary,
        )
