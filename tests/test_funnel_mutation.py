"""Precision tests for funnelsim: defaults, arithmetic, boundaries, fail-closed paths.

Mutation-grade complements to the behavioral tests: every default value,
every fail-closed raise, intervention window boundaries, series arithmetic,
and the CLI's error paths. Fast by design: direct unit calls plus tiny
engine runs; the two heavier tests are the seed-characterization runs.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import sys
from datetime import timedelta

import pytest
import yaml

from eve_miro.core.simulation.engine import get_simulation_engine
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured
from funnelsim.agents import CustomerAgent, CustomerState, MoverOfficeAgent
from funnelsim.economics import (
    Pricing,
    expected_texts_per_loop,
    loop_variable_cost,
    monthly_fixed_cost,
)
from funnelsim.engine import (
    FunnelSimEngine,
    _DayTotals,
    _intervention_day,
    _positive_float,
)
from funnelsim.scenarios import funnel_scenario


def _eng() -> FunnelSimEngine:
    return FunnelSimEngine(scenario=_bare_scenario())


def _world() -> WorldState:
    return WorldState(
        world_id="test",
        timestamp="2026-10-01T00:00:00Z",
        information_cutoff="2026-10-01T00:00:00Z",
    )


def _bare_scenario(mode: str = "post_job", *, agents: dict | None = None, **conditions) -> Scenario:
    """Raw Scenario bypassing the builder, so engine defaults are exercised."""
    base = {"mode": mode}
    if mode == "post_job":
        base["jobs_per_month"] = 60.0
    base.update(conditions)
    return Scenario(
        name="bare",
        type="funnel",
        initial_world={"source": "fixture", "timestamp": "2026-10-01T00:00:00Z"},
        duration={"simulated_days": 30, "simulated_hours": 720},
        agents=agents if agents is not None else {"population": 1},
        conditions=base,
        random_seed=1,
        information_cutoff="2026-10-01T00:00:00Z",
    )


async def _ainit(days: int = 30, movers: int = 1, pop: int | None = None, **kw):
    kw.setdefault("simulated_days", days)
    kw.setdefault("movers", movers)
    seed = kw.pop("seed", 11)
    sc = funnel_scenario("t", random_seed=seed, **kw)
    eng = FunnelSimEngine(scenario=sc)
    sim = await eng.initialize(_world(), Population(synthetic_n=movers if pop is None else pop))
    return eng, sim


def _init(*args, **kwargs):
    return asyncio.run(_ainit(*args, **kwargs))


# ---------------------------------------------------------------- agents


def test_customer_agent_field_defaults():
    c = CustomerAgent(agent_id="a", mover_id="m")
    assert c.state is CustomerState.UNCONTACTED
    assert c.day_texted == -1
    assert c.day_terminal == -1
    assert c.texts_sent == 0
    assert c.flagged is False


def test_office_agent_defaults():
    o = MoverOfficeAgent(mover_id="m")
    assert o.response_days_mean == 2.0
    assert o.resolve_prob == 0.70


def test_office_unresolved_latency_is_exactly_zero():
    o = MoverOfficeAgent(mover_id="m", resolve_prob=0.0, rng=random.Random(3))
    resolved, latency = o.attempt_resolve()
    assert resolved is False
    assert latency == 0.0


def test_office_resolve_latency_follows_seed_stream():
    seed = 11
    o = MoverOfficeAgent(mover_id="m", resolve_prob=1.0, response_days_mean=2.0, rng=random.Random(seed))
    resolved, latency = o.attempt_resolve()
    check = random.Random(seed)
    check.random()  # the resolve-prob draw
    assert resolved is True
    assert latency == pytest.approx(check.expovariate(1.0 / 2.0))


def test_office_resolve_latency_respects_floor():
    seed = 11
    o = MoverOfficeAgent(mover_id="m", resolve_prob=1.0, response_days_mean=0.01, rng=random.Random(seed))
    _, latency = o.attempt_resolve()
    check = random.Random(seed)
    check.random()
    # floor: max(0.01, 0.05) -> rate 1/0.05
    assert latency == pytest.approx(check.expovariate(1.0 / 0.05))


# ---------------------------------------------------------------- economics


def test_pricing_defaults():
    p = Pricing()
    assert p.per_job == 0.80
    assert p.per_review_bonus == 5.00
    assert p.per_problem_bonus == 10.00
    assert p.per_booking_bonus == 25.00
    assert p.text_cost == 0.013
    assert p.dlc_setup == 19.50
    assert p.dlc_monthly_fee == 2.00
    assert p.dlc_amort_months == 12


def test_monthly_fixed_cost_exact():
    assert monthly_fixed_cost(Pricing()) == pytest.approx(19.50 / 12 + 2.00)
    assert monthly_fixed_cost(
        Pricing(dlc_setup=120.0, dlc_monthly_fee=10.0, dlc_amort_months=12)
    ) == pytest.approx(20.0)
    # zero amortization window falls back to a single month, never div-by-zero
    assert monthly_fixed_cost(
        Pricing(dlc_setup=12.0, dlc_monthly_fee=1.0, dlc_amort_months=0)
    ) == pytest.approx(13.0)


def test_loop_variable_cost_exact():
    assert loop_variable_cost(100, Pricing()) == pytest.approx(1.30)
    assert loop_variable_cost(0, Pricing()) == 0.0


def test_expected_texts_per_loop():
    assert expected_texts_per_loop() == pytest.approx(3.2)
    assert expected_texts_per_loop(0.5) == pytest.approx(3.5)
    assert expected_texts_per_loop(0.0) == pytest.approx(3.0)


# ---------------------------------------------------------------- helpers


def test_intervention_day_parses_days_and_hours():
    assert _intervention_day({"timestamp": "+5d"}) == 5
    assert _intervention_day({"timestamp": "+72h"}) == 3
    assert _intervention_day({"timestamp": "+0d"}) == 0


def test_intervention_day_rejects_garbage():
    assert _intervention_day({}) is None
    assert _intervention_day({"timestamp": ""}) is None
    assert _intervention_day({"timestamp": "tomorrow"}) is None
    assert _intervention_day({"timestamp": "-5d"}) is None
    assert _intervention_day({"timestamp": "+xh"}) is None  # hits the ValueError branch


def test_positive_float_accepts_zero_and_numeric_string():
    assert _positive_float(0, "x") == 0.0
    assert _positive_float("3.5", "x") == 3.5


def test_positive_float_rejects_text():
    with pytest.raises(EngineNotConfigured, match="must be a number"):
        _positive_float("abc", "x")


def test_positive_float_rejects_negative():
    with pytest.raises(EngineNotConfigured, match="must be non-negative"):
        _positive_float(-2.0, "x")


def test_arrivals_exact_rate():
    eng = _eng()
    assert eng._arrivals(2.0, random.Random(0)) == 2
    assert eng._arrivals(0.0, random.Random(0)) == 0


def test_arrivals_fractional_draw():
    eng = _eng()
    # Random(1).random() == 0.134... < 0.5 -> rounds up; Random(0) -> 0.844... -> stays
    assert eng._arrivals(2.5, random.Random(1)) == 3
    assert eng._arrivals(2.5, random.Random(0)) == 2


# ---------------------------------------------------------------- _params_from


def _params(**conditions):
    eng = FunnelSimEngine(scenario=_bare_scenario())
    return eng._params_from(_bare_scenario(**conditions))


def test_params_from_applies_all_post_job_defaults():
    p = _params()
    assert p.mode == "post_job"
    assert p.jobs_per_month == 60.0
    assert p.contactable_coverage == 0.80
    assert p.review_conversion == 0.20
    assert p.opt_out_rate == 0.01
    assert p.problem_rate == 0.20
    assert p.problem_resolve_prob == 0.70
    assert p.office_response_days_mean == 2.0
    assert p.pricing == Pricing()


def test_params_from_applies_all_speed_to_lead_defaults():
    eng = FunnelSimEngine(scenario=_bare_scenario(mode="speed_to_lead"))
    p = eng._params_from(_bare_scenario(mode="speed_to_lead"))
    assert p.mode == "speed_to_lead"
    assert p.leads_per_day == 10.0
    assert p.contactable_coverage == 0.80
    assert p.response_mean_covered_min == 1.0
    assert p.response_mean_uncovered_min == 8.0
    assert p.book_prob_fast == 0.55
    assert p.book_prob_slow == 0.15


def test_params_from_rejects_zero_jobs_per_month():
    with pytest.raises(EngineNotConfigured, match="must be positive"):
        _params(jobs_per_month=0)


def test_params_from_allows_fractional_jobs_per_month():
    assert _params(jobs_per_month=0.5).jobs_per_month == 0.5


@pytest.mark.parametrize(
    "key",
    [
        "contactable_coverage",
        "review_conversion",
        "opt_out_rate",
        "problem_rate",
        "problem_resolve_prob",
    ],
)
def test_params_from_rejects_probability_over_one(key):
    with pytest.raises(EngineNotConfigured, match="must be <= 1"):
        _params(**{key: 1.5})


def test_params_from_rejects_zero_leads_per_day():
    eng = FunnelSimEngine(scenario=_bare_scenario(mode="speed_to_lead"))
    with pytest.raises(EngineNotConfigured, match="leads_per_day must be positive"):
        eng._params_from(_bare_scenario(mode="speed_to_lead", leads_per_day=0))


def test_params_from_rejects_non_mapping_pricing():
    with pytest.raises(EngineNotConfigured, match="pricing must be a mapping"):
        _params(pricing="nope")


def test_params_from_pricing_overrides():
    p = _params(pricing={"per_job": 2.5, "text_cost": 0.02})
    assert p.pricing.per_job == 2.5
    assert p.pricing.text_cost == 0.02
    assert p.pricing.per_review_bonus == 5.00  # untouched default


# ---------------------------------------------------------------- initialize


def test_initialize_days_fallback_to_simulated_hours():
    sc = Scenario(
        name="bare",
        type="funnel",
        initial_world={"source": "fixture", "timestamp": "2026-10-01T00:00:00Z"},
        duration={"simulated_days": 0, "simulated_hours": 48},
        agents={"population": 1},
        conditions={"mode": "speed_to_lead"},  # no simulated_days key
        random_seed=1,
        information_cutoff="2026-10-01T00:00:00Z",
    )
    eng = FunnelSimEngine(scenario=sc)
    sim = asyncio.run(eng.initialize(_world(), Population(synthetic_n=1)))
    assert sim.hours == 48


def test_initialize_minimum_one_day():
    sc = Scenario(
        name="bare",
        type="funnel",
        initial_world={"source": "fixture", "timestamp": "2026-10-01T00:00:00Z"},
        duration={"simulated_days": 0, "simulated_hours": 0},
        agents={"population": 1},
        conditions={"mode": "speed_to_lead"},
        random_seed=1,
        information_cutoff="2026-10-01T00:00:00Z",
    )
    eng = FunnelSimEngine(scenario=sc)
    sim = asyncio.run(eng.initialize(_world(), Population(synthetic_n=1)))
    assert sim.hours == 24


def test_initialize_movers_prefers_explicit_population():
    eng, sim = _init(days=5, movers=2, pop=5, seed=11)
    # synthetic_n=5 overrides the scenario's population=2
    assert sim.population_n == 5
    assert sim.world_snapshot["n_movers"] == 5


def test_initialize_movers_default_three():
    # agents.population=0 is falsy -> falls back to 3 (the property defaults
    # missing keys to 200, so the fallback needs an explicit 0)
    sc = _bare_scenario(mode="speed_to_lead", agents={"population": 0})
    eng = FunnelSimEngine(scenario=sc)
    sim = asyncio.run(eng.initialize(_world(), Population(synthetic_n=0)))
    assert sim.population_n == 3


def test_initialize_copies_seed_type_and_disclaimer():
    eng, sim = _init(days=5, movers=1, seed=4242)
    assert sim.seed == 4242
    assert sim.scenario_type == "funnel"
    assert sim.world_snapshot["mode"] == "post_job"
    assert "SIMULATED" in sim.disclaimer
    assert sim.interventions == []


# ---------------------------------------------------------------- interventions


async def _aistate(interventions, **kw):
    kw.setdefault("simulated_days", 30)
    kw.setdefault("movers", 1)
    kw.setdefault("random_seed", 11)
    sc = funnel_scenario("t", interventions=interventions, **kw)
    eng = FunnelSimEngine(scenario=sc)
    sim = await eng.initialize(_world(), Population(synthetic_n=kw["movers"]))
    return eng, sim, eng._state(sim)


def _istate(*args, **kwargs):
    return asyncio.run(_aistate(*args, **kwargs))


def test_carrier_crackdown_applies_only_on_its_day():
    eng, sim, st = _istate(
        [
            {
                "type": "carrier_crackdown",
                "timestamp": "+5d",
                "extra": {"opt_out_multiplier": 10.0, "duration_days": 25},
            }
        ]
    )
    eng._apply_interventions(sim, st, 0)
    assert st.windows.opt_out_multiplier == 1.0
    eng._apply_interventions(sim, st, 5)
    assert st.windows.opt_out_multiplier == 10.0
    assert st.windows.opt_out_until_day == 30


def test_carrier_crackdown_defaults():
    eng, sim, st = _istate([{"type": "carrier_crackdown", "timestamp": "+0d"}])
    eng._apply_interventions(sim, st, 0)
    assert st.windows.opt_out_multiplier == 5.0
    assert st.windows.opt_out_until_day == 14


def test_google_enforcement_sets_cap_exactly():
    eng, sim, st = _istate([{"type": "google_enforcement", "timestamp": "+0d"}])
    eng._apply_interventions(sim, st, 0)
    assert st.windows.review_cap_per_day == 3.0
    assert st.windows.review_cap_until_day == 10**9


def test_office_slowdown_scales_response_mean():
    eng, sim, st = _istate([{"type": "office_slowdown", "timestamp": "+0d"}], office_response_days_mean=2.0)
    eng._apply_interventions(sim, st, 0)
    assert st.windows.office_slowdown_mult == 3.0
    assert st.windows.office_slowdown_until_day == 30
    for office in st.offices.values():
        assert office.response_days_mean == pytest.approx(6.0)


def test_unknown_intervention_type_is_ignored():
    eng, sim, st = _istate([{"type": "mystery", "timestamp": "+0d", "extra": {"opt_out_multiplier": 99.0}}])
    eng._apply_interventions(sim, st, 0)
    w = st.windows
    assert w.opt_out_multiplier == 1.0
    assert w.review_cap_per_day == math.inf
    assert w.office_slowdown_mult == 1.0


def test_expire_windows_opt_out_boundary():
    eng, sim, st = _istate(
        [
            {
                "type": "carrier_crackdown",
                "timestamp": "+0d",
                "extra": {"opt_out_multiplier": 5.0, "duration_days": 5},
            }
        ]
    )
    eng._apply_interventions(sim, st, 0)
    assert st.windows.opt_out_until_day == 5
    eng._expire_windows(st, 4)
    assert st.windows.opt_out_multiplier == 5.0  # still active the day before
    eng._expire_windows(st, 5)
    assert st.windows.opt_out_multiplier == 1.0
    assert st.windows.opt_out_until_day == -1


def test_expire_windows_zero_day_window():
    eng, sim, st = _istate([])
    st.windows.opt_out_until_day = 0
    st.windows.opt_out_multiplier = 5.0
    eng._expire_windows(st, 0)
    assert st.windows.opt_out_multiplier == 1.0
    assert st.windows.opt_out_until_day == -1


def test_expire_windows_clears_cap_and_slowdown():
    eng, sim, st = _istate(
        [
            {
                "type": "google_enforcement",
                "timestamp": "+0d",
                "extra": {"max_reviews_per_day": 2.0, "duration_days": 7},
            },
            {
                "type": "office_slowdown",
                "timestamp": "+0d",
                "extra": {"response_time_multiplier": 3.0, "duration_days": 9},
            },
        ],
        office_response_days_mean=2.0,
    )
    eng._apply_interventions(sim, st, 0)
    eng._expire_windows(st, 7)
    assert st.windows.review_cap_per_day == math.inf
    assert st.windows.review_cap_until_day == -1
    # slowdown still active until day 9
    assert st.windows.office_slowdown_mult == 3.0
    eng._expire_windows(st, 9)
    assert st.windows.office_slowdown_mult == 1.0
    assert st.windows.office_slowdown_until_day == -1
    for office in st.offices.values():
        assert office.response_days_mean == pytest.approx(2.0)


# ---------------------------------------------------------------- stepping: post_job


def test_step_post_job_arrival_rate_uses_30_day_month():
    eng, sim = _init(days=30, movers=1, seed=5, jobs_per_month=30.0, contactable_coverage=1.0)
    st = eng._state(sim)
    st.rng = random.Random(52)  # first draw 0.978... >= 30/31: mutant rate would give 0
    tot = eng._step_post_job(st, 0)
    assert tot.jobs == 1


def test_step_post_job_first_day_texts_exact():
    eng, sim = _init(days=30, movers=1, seed=5, jobs_per_month=30.0, contactable_coverage=1.0)
    st = eng._state(sim)
    st.rng = random.Random(0)
    tot = eng._step_post_job(st, 0)
    assert (tot.jobs, tot.contacted, tot.texts) == (1, 1, 2)


def test_post_job_exact_counts_seed99():
    """Characterization: pins the rng stream, incl. per-customer seeding."""
    eng, sim = _init(
        days=30,
        movers=1,
        seed=99,
        jobs_per_month=30.0,
        contactable_coverage=1.0,
        review_conversion=0.2,
        opt_out_rate=0.01,
        problem_rate=0.2,
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=30 * 24)))
    s = result.summary
    assert s["jobs"] == 30
    assert s["contacted"] == 30
    assert s["reviews_gained"] == 3
    assert s["problems_routed"] == 8
    assert s["problems_resolved"] == 7
    assert s["opt_outs"] == 0
    assert s["cost"] == 5.07
    assert s["revenue"] == 109.0
    ps = result.predicted_series
    assert len(ps["cost"]) == 30
    assert ps["cost"][-1] == 5.068  # series keeps round(cum, 4); summary rounds to 2dp
    assert ps["revenue"][-1] == 109.0
    assert ps["reviews_per_100"][-1] == pytest.approx(10.0)


def test_nudge_then_resolve_timing():
    eng, sim = _init(
        days=5,
        movers=1,
        seed=5,
        jobs_per_month=30.0,  # exactly one arrival per day
        contactable_coverage=1.0,
        review_conversion=1.0,
        opt_out_rate=0.0,
        problem_rate=0.0,
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=5 * 24)))
    s = result.summary
    # day-0 customer: texted day 0, nudged day 3, resolved (review) day 4
    assert s["reviews_gained"] == 1
    st = eng._state(sim)
    cust = st.customers["mover-00-c000000"]
    assert cust.state is CustomerState.REVIEWED
    assert cust.texts_sent == 3  # thank-you + ask + nudge, no extra on review


def test_weekly_summary_text_count():
    eng, sim = _init(
        days=14,
        movers=1,
        seed=5,
        jobs_per_month=30.0,
        contactable_coverage=1.0,
        review_conversion=1.0,
        opt_out_rate=0.0,
        problem_rate=0.0,
        pricing={
            "per_job": 0.0,
            "per_review_bonus": 0.0,
            "per_problem_bonus": 0.0,
            "text_cost": 1.0,
            "dlc_setup": 0.0,
            "dlc_monthly_fee": 0.0,
        },
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=14 * 24)))
    # 14 contacts x2 + 11 nudges + weekly summaries on days 6 and 13 (4 each)
    assert result.summary["cost"] == 47.0


# ---------------------------------------------------------------- stepping: speed_to_lead


def test_speed_to_lead_exact_counts_seed7():
    """Characterization: pins lead counts, texts, bookings, economics."""
    eng, sim = _init(
        days=10,
        movers=1,
        seed=7,
        mode="speed_to_lead",
        leads_per_day=5.0,
        contactable_coverage=1.0,
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=10 * 24)))
    s = result.summary
    assert s["leads"] == 50
    assert s["bookings"] == 35
    assert s["cost"] == pytest.approx(0.65)  # 50 texts x $0.013
    assert s["revenue"] == pytest.approx(875.0)  # 35 x $25


def test_speed_to_lead_no_coverage_no_texts():
    eng, sim = _init(
        days=5,
        movers=1,
        seed=7,
        mode="speed_to_lead",
        leads_per_day=5.0,
        contactable_coverage=0.0,
    )
    asyncio.run(eng.run(sim, sim.origin + timedelta(hours=5 * 24)))
    st = eng._state(sim)
    assert st.cum.texts == 0
    assert st.cum.leads == 25


# ---------------------------------------------------------------- step / run


def test_step_t_and_hour_advance():
    eng, sim = _init(days=5, movers=1, seed=5)
    s0 = asyncio.run(eng.step(sim))
    assert s0.t == sim.origin + timedelta(days=0)
    assert s0.hour == 0
    s1 = asyncio.run(eng.step(sim))
    assert s1.t == sim.origin + timedelta(days=1)
    assert s1.hour == 24
    assert sim.cursor_hour == 48
    assert "jobs=" in s1.actions[0].outcome


def test_step_expires_intervention_windows():
    eng, sim, st = _istate(
        [
            {
                "type": "carrier_crackdown",
                "timestamp": "+0d",
                "extra": {"opt_out_multiplier": 9.0, "duration_days": 1},
            }
        ]
    )
    asyncio.run(eng.step(sim))  # day 0: applied (until day 1), not yet expired
    assert st.windows.opt_out_multiplier == 9.0
    asyncio.run(eng.step(sim))  # day 1: expiry clears it
    assert st.windows.opt_out_multiplier == 1.0


def test_step_resets_daily_review_counter():
    eng, sim = _init(
        days=6,
        movers=1,
        seed=5,
        jobs_per_month=60.0,  # two arrivals per day
        contactable_coverage=1.0,
        review_conversion=1.0,
        opt_out_rate=0.0,
        problem_rate=0.0,
        interventions=[
            {
                "type": "google_enforcement",
                "timestamp": "+0d",
                "extra": {"max_reviews_per_day": 0.5},
            }
        ],
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=6 * 24)))
    s = result.summary
    # cap 0.5: first review each day counts (counter reset), the second is flagged
    assert s["reviews_gained"] == 2
    assert s["reviews_flagged"] == 2


def test_step_posts_monthly_fixed_cost_once_per_month():
    eng, sim = _init(
        days=60,
        movers=1,
        seed=5,
        jobs_per_month=30.0,
        pricing={
            "per_job": 0.0,
            "per_review_bonus": 0.0,
            "per_problem_bonus": 0.0,
            "text_cost": 0.0,
            "dlc_setup": 120.0,
            "dlc_monthly_fee": 10.0,
        },
    )
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=60 * 24)))
    # $20/mover posted on days 29 and 59 only
    assert result.summary["cost"] == 40.0
    assert result.summary["revenue"] == 0.0


def test_run_pauses_at_until():
    eng, sim = _init(days=30, movers=1, seed=5)
    result = asyncio.run(eng.run(sim, sim.origin + timedelta(hours=4.5 * 24)))
    assert sim.status == "paused"
    assert len(sim.steps) == 5
    assert result.summary["days"] == 5


def test_run_until_on_step_boundary_includes_boundary_day():
    eng, sim = _init(days=30, movers=1, seed=5)
    asyncio.run(eng.run(sim, sim.origin + timedelta(hours=5 * 24)))
    # t == until does not stop the loop; only t > until does -> 6 days stepped
    assert len(sim.steps) == 6


def test_run_completes_full_horizon():
    eng, sim = _init(days=5, movers=1, seed=5)
    asyncio.run(eng.run(sim, sim.origin + timedelta(hours=30 * 24)))
    assert sim.status == "completed"
    assert len(sim.steps) == 5


def test_run_remaps_renamed_simulation_id():
    eng, sim = _init(days=5, movers=1, seed=5)
    renamed = sim.model_copy(update={"id": "renamed-id"})
    result = asyncio.run(eng.run(renamed, renamed.origin + timedelta(hours=5 * 24)))
    assert result.summary["days"] == 5
    assert renamed.status == "completed"


# ---------------------------------------------------------------- _result


def test_result_series_and_summary_arithmetic():
    eng, sim = _init(days=2, movers=1, seed=5)
    st = eng._state(sim)
    st.day = 2
    st.daily = [
        _DayTotals(
            jobs=100,
            contacted=80,
            texts=250,
            reviews=20,
            reviews_flagged=2,
            problems_routed=10,
            problems_resolved=7,
            opt_outs=4,
        ),
        _DayTotals(
            jobs=100,
            contacted=80,
            texts=250,
            reviews=10,
            reviews_flagged=1,
            problems_routed=5,
            problems_resolved=3,
            opt_outs=2,
        ),
    ]
    st.cum = _DayTotals(
        jobs=200,
        contacted=160,
        texts=500,
        reviews=30,
        reviews_flagged=3,
        problems_routed=15,
        problems_resolved=10,
        opt_outs=6,
    )
    st.cost_cum = 12.5
    st.revenue_cum = 300.0
    st.cost_series = [6.0, 12.5]
    st.revenue_series = [150.0, 300.0]
    res = eng._result(sim)
    ps = res.predicted_series
    assert ps["reviews_per_100"] == [20.0, 15.0]
    assert ps["problems_routed"] == [10.0, 15.0]
    assert ps["opt_out_rate"] == [0.05, 0.0375]
    assert ps["cost"] == [6.0, 12.5]
    assert ps["revenue"] == [150.0, 300.0]
    assert "bookings_per_100_leads" not in ps
    s = res.summary
    assert s["jobs"] == 200
    assert s["contacted"] == 160
    assert s["reviews_gained"] == 30
    assert s["reviews_flagged"] == 3
    assert s["conversion"] == round(30 / 160, 4)
    assert s["opt_out_rate"] == round(6 / 160, 4)
    assert s["incremental_share_pp"] == 15.0
    assert s["implied_total_share_pp"] == 33.0
    assert s["problems_routed"] == 15
    assert s["problems_resolved"] == 10
    assert s["opt_outs"] == 6
    assert s["cost"] == 12.5
    assert s["revenue"] == 300.0
    assert s["margin"] == 287.5
    assert s["margin_pct"] == round(100 * 287.5 / 300, 1)
    assert s["projection_only"] is True
    assert s["observed_t1"] is None


# ---------------------------------------------------------------- scenarios builder


def test_funnel_scenario_builder_defaults():
    sc = funnel_scenario("x")
    assert sc.type == "funnel"
    assert sc.conditions["mode"] == "post_job"
    assert sc.conditions["simulated_days"] == 90
    assert sc.conditions["jobs_per_month"] == 60.0
    assert sc.conditions["contactable_coverage"] == 0.80
    assert sc.conditions["review_conversion"] == 0.20
    assert sc.conditions["opt_out_rate"] == 0.01
    assert sc.conditions["problem_rate"] == 0.20
    assert sc.conditions["problem_resolve_prob"] == 0.70
    assert sc.conditions["office_response_days_mean"] == 2.0
    assert sc.conditions["leads_per_day"] == 10.0
    assert sc.conditions["pricing"] == {}
    assert sc.random_seed == 20261016
    assert sc.duration["simulated_hours"] == 90 * 24
    assert sc.agents["population"] == 3
    assert sc.interventions == []
    assert "SIMULATED" in sc.disclaimer


def test_funnel_scenario_builder_overrides():
    sc = funnel_scenario(
        "y",
        mode="speed_to_lead",
        simulated_days=14,
        movers=1,
        interventions=[{"type": "carrier_crackdown", "timestamp": "+1d"}],
    )
    assert sc.conditions["mode"] == "speed_to_lead"
    assert sc.duration["simulated_hours"] == 14 * 24
    assert sc.agents["population"] == 1
    assert len(sc.interventions) == 1
    assert sc.interventions[0].type == "carrier_crackdown"


# ---------------------------------------------------------------- CLI internals


def test_cli_fail_returns_one(capsys):
    import eve_miro.cli.funnel_sim as cli

    assert cli.fail("boom") == 1
    assert "error: boom" in capsys.readouterr().err


def test_cli_list_scenarios_empty_dir(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    d = tmp_path / "experiments" / "funnel"
    d.mkdir(parents=True)
    (d / "broken.yaml").write_text("not: [valid", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    # a lone broken file must be skipped, not crash nor leak a stale doc
    assert cli.list_scenarios() == []


def test_cli_write_summary_exact(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    summary = {"a": 1, "b": [1, 2]}
    path = cli.write_funnel_summary(summary)
    assert path == tmp_path / "storage" / "funnel" / "latest_funnel_run.json"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == json.dumps(summary, indent=2)


def test_cli_load_fixture_missing_keys(tmp_path):
    import eve_miro.cli.funnel_sim as cli

    d = tmp_path / "fx"
    d.mkdir()
    (d / "funnel_baseline.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    with pytest.raises(EngineNotConfigured, match="missing keys"):
        cli._load_fixture(d)


def test_cli_load_fixture_absent_file(tmp_path):
    import eve_miro.cli.funnel_sim as cli

    with pytest.raises(FileNotFoundError, match="missing fixture"):
        cli._load_fixture(tmp_path / "absent")


def test_cli_load_scenario_doc_missing():
    import eve_miro.cli.funnel_sim as cli

    with pytest.raises(FileNotFoundError, match="missing scenario definition"):
        cli._load_scenario_doc("definitely_not_a_scenario")


def test_cli_load_scenario_doc_not_a_mapping(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    d = tmp_path / "experiments" / "funnel"
    d.mkdir(parents=True)
    (d / "list.yaml").write_text("[1, 2]\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="did not parse to a mapping"):
        cli._load_scenario_doc("list")


def test_cli_scenario_kwargs_defaults():
    import eve_miro.cli.funnel_sim as cli

    kw = cli._scenario_kwargs({}, days=30, seed=5)
    assert kw["mode"] == "post_job"
    assert kw["simulated_days"] == 30
    assert kw["movers"] == 3
    assert kw["random_seed"] == 5
    assert kw["jobs_per_month"] == 60.0
    assert kw["contactable_coverage"] == 0.80
    assert kw["review_conversion"] == 0.20
    assert kw["opt_out_rate"] == 0.01
    assert kw["problem_rate"] == 0.20
    assert kw["problem_resolve_prob"] == 0.70
    assert kw["office_response_days_mean"] == 2.0
    assert kw["leads_per_day"] == 10.0
    assert kw["origin"] == "2026-10-01T00:00:00Z"


def test_cli_scenario_kwargs_agents_population():
    import eve_miro.cli.funnel_sim as cli

    kw = cli._scenario_kwargs({"agents": {"population": 2}}, days=30, seed=5)
    assert kw["movers"] == 2


def _write_cli_dirs(tmp_path):
    exp = tmp_path / "experiments" / "funnel"
    exp.mkdir(parents=True)
    (exp / "mini.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "mini",
                "type": "funnel",
                "information_cutoff": "2026-10-01T00:00:00Z",
                # no random_seed -> default 20261016; no agents -> 3 movers
                "conditions": {"mode": "post_job", "jobs_per_month": 60.0},
            }
        ),
        encoding="utf-8",
    )
    fx = tmp_path / "fixtures"
    fx.mkdir()
    (fx / "funnel_baseline.json").write_text(
        json.dumps(
            {
                "baseline_review_share": 0.18,
                "gatherup_conversion_per_100_requests": [15, 20, 26],
                "text_cost_all_in": 0.013,
                "provenance": {"source": "test"},
            }
        ),
        encoding="utf-8",
    )
    return fx


def test_cli_run_scenario_seed_day_and_mean_math(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    fx = _write_cli_dirs(tmp_path)
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    summary = asyncio.run(cli._run_scenario("mini", 1, fx))
    assert summary["seeds"] == [20261016, 20261017]
    assert summary["movers"] == 3
    assert summary["days"] == 30
    assert len(summary["mean_series"]["cost"]) == 30
    assert len(summary["mean_series"]["reviews_per_100"]) == 30
    # metrics are seed-means: cross-check against the mean cost/revenue tails.
    # Loose tolerance: the series is rounded per-seed then averaged, while
    # metrics average unrounded values. Still kills a mean<->2x-sum mutant.
    assert summary["metrics"]["cost"] == pytest.approx(summary["mean_series"]["cost"][-1], abs=0.01)
    assert summary["metrics"]["revenue"] == pytest.approx(summary["mean_series"]["revenue"][-1], abs=0.01)
    assert summary["metrics"]["margin"] == pytest.approx(
        summary["metrics"]["revenue"] - summary["metrics"]["cost"], abs=0.01
    )


def _fake_summary(**over):
    m = {
        "jobs": 10,
        "reviews_gained": 2.0,
        "incremental_share_pp": 1.0,
        "implied_total_share_pp": 19.0,
        "conversion": 0.2,
        "problems_routed": 1.0,
        "problems_resolved": 1.0,
        "opt_out_rate": 0.01,
        "bookings": 0.0,
        "cost": 1.0,
        "revenue": 10.0,
        "margin": 9.0,
        "margin_pct": 90.0,
    }
    return {
        "scenario": "funnel_base_001",
        "months": 1,
        "mode": "post_job",
        "movers": 1,
        "cutoff": "2026-10-01T00:00:00Z",
        "seeds": [1, 2],
        "metrics": m,
        "ledger_record_id": "rec-1",
        "ledger_verdict": "PENDING",
        "disclaimer": "SIMULATED.",
        **over,
    }


def test_cli_cmd_default_scenario_is_first_registered(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli
    from eve_miro.paths import REPO_ROOT

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    (tmp_path / "experiments").symlink_to(REPO_ROOT / "experiments", target_is_directory=True)
    (tmp_path / "datasets").symlink_to(REPO_ROOT / "datasets", target_is_directory=True)
    seen = {}
    monkeypatch.setattr(
        cli, "run_funnel_scenario", lambda s, m, f=None: seen.update(scenario=s) or _fake_summary()
    )
    assert cli.cmd_funnel_sim([]) == 0
    assert seen["scenario"] == "funnel_base_001"


def test_cli_cmd_no_scenarios_fails_closed(tmp_path, monkeypatch):
    import eve_miro.cli.funnel_sim as cli

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SCENARIOS", ())
    assert cli.cmd_funnel_sim([]) == 1


def test_cli_cmd_rejects_zero_months():
    import eve_miro.cli.funnel_sim as cli

    assert cli.cmd_funnel_sim(["--months", "0"]) == 1


@pytest.mark.parametrize("exc", [FileNotFoundError("gone"), EngineNotConfigured("bad"), ValueError("bad")])
def test_cli_cmd_maps_run_errors_to_exit_one(tmp_path, monkeypatch, exc):
    import eve_miro.cli.funnel_sim as cli
    from eve_miro.paths import REPO_ROOT

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    (tmp_path / "experiments").symlink_to(REPO_ROOT / "experiments", target_is_directory=True)
    (tmp_path / "datasets").symlink_to(REPO_ROOT / "datasets", target_is_directory=True)

    def _raise(s, m, f=None):
        raise exc

    monkeypatch.setattr(cli, "run_funnel_scenario", _raise)
    assert cli.cmd_funnel_sim(["--scenario", "funnel_base_001", "--months", "1"]) == 1


# ---------------------------------------------------------------- routing


def test_routing_none_returns_stub():
    eng = get_simulation_engine(None)
    assert eng.name == "stub"


def test_routing_other_type_returns_mirofish(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    sc = _bare_scenario()
    sc = sc.model_copy(update={"type": "typhoon"})
    eng = get_simulation_engine(sc)
    assert eng.name == "mirofish"


def test_routing_market_import_error_fails_closed(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    monkeypatch.setitem(sys.modules, "marketsim.engine", None)
    from marketsim.scenarios import market_scenario

    with pytest.raises(EngineNotConfigured, match="marketsim engine not installed"):
        get_simulation_engine(market_scenario("m", ["ACME"]))


def test_routing_funnel_import_error_fails_closed(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    monkeypatch.setitem(sys.modules, "funnelsim.engine", None)
    with pytest.raises(EngineNotConfigured, match="funnelsim engine not installed"):
        get_simulation_engine(funnel_scenario("t"))
