"""Engine tests for funnelsim: determinism, fail-closed paths, interventions."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from eve_miro.core.simulation.engine import get_simulation_engine
from eve_miro.core.world.state import Population, WorldState
from eve_miro.errors import EngineNotConfigured
from funnelsim.engine import FunnelSimEngine
from funnelsim.scenarios import funnel_scenario


def _world() -> WorldState:
    return WorldState(
        world_id="test",
        timestamp="2026-10-01T00:00:00Z",
        information_cutoff="2026-10-01T00:00:00Z",
    )


async def _run(seed: int = 20261016, **kw) -> dict:
    kw.setdefault("simulated_days", 30)
    kw.setdefault("movers", 2)
    sc = funnel_scenario("t", random_seed=seed, **kw)
    engine = FunnelSimEngine(scenario=sc)
    sim = await engine.initialize(_world(), Population(synthetic_n=kw["movers"]))
    result = await engine.run(sim, sim.origin + timedelta(hours=kw["simulated_days"] * 24))
    return result


def test_same_seed_identical_output():
    r1 = _run_sync(seed=11)
    r2 = _run_sync(seed=11)
    assert r1["summary"] == r2["summary"]
    assert r1["predicted_series"] == r2["predicted_series"]


def _run_sync(seed: int = 20261016, **kw) -> dict:
    import asyncio

    result = asyncio.run(_run(seed=seed, **kw))
    return {"summary": result.summary, "predicted_series": result.predicted_series}


def test_different_seeds_differ():
    r1 = _run_sync(seed=11)
    r2 = _run_sync(seed=12)
    assert r1["summary"]["reviews_gained"] != r2["summary"]["reviews_gained"]


def test_predicted_series_keys():
    r = _run_sync()
    for key in ("reviews_per_100", "problems_routed", "cost", "revenue", "opt_out_rate"):
        assert key in r["predicted_series"], key
        assert len(r["predicted_series"][key]) == 30


def test_no_scenario_fails_closed():
    import asyncio

    engine = FunnelSimEngine(scenario=None)
    with pytest.raises(EngineNotConfigured):
        asyncio.run(engine.initialize(_world(), Population(synthetic_n=2)))


def test_unknown_mode_fails_closed():
    import asyncio

    sc = funnel_scenario("t", mode="telepathy")
    engine = FunnelSimEngine(scenario=sc)
    with pytest.raises(EngineNotConfigured):
        asyncio.run(engine.initialize(_world(), Population(synthetic_n=2)))


def test_missing_jobs_per_month_fails_closed():
    import asyncio

    from eve_miro.core.simulation.scenarios import Scenario

    sc = Scenario(
        name="bad",
        type="funnel",
        initial_world={"source": "fixture", "timestamp": "2026-10-01T00:00:00Z"},
        duration={"simulated_days": 30, "simulated_hours": 720},
        agents={"population": 2},
        conditions={"mode": "post_job"},  # no jobs_per_month
        random_seed=1,
        information_cutoff="2026-10-01T00:00:00Z",
    )
    engine = FunnelSimEngine(scenario=sc)
    with pytest.raises(EngineNotConfigured):
        asyncio.run(engine.initialize(_world(), Population(synthetic_n=2)))


def test_probabilities_summing_over_one_fail_closed():
    import asyncio

    sc = funnel_scenario("t", opt_out_rate=0.5, problem_rate=0.4, review_conversion=0.3)
    engine = FunnelSimEngine(scenario=sc)
    with pytest.raises(EngineNotConfigured):
        asyncio.run(engine.initialize(_world(), Population(synthetic_n=2)))


def test_step_before_initialize_fails_closed():
    import asyncio

    sc = funnel_scenario("t")
    engine = FunnelSimEngine(scenario=sc)
    sim_holder: dict = {}

    async def _go():
        from eve_miro.core.simulation.engine import Simulation

        fake = Simulation(
            id="nope",
            world_id="w",
            scenario_name="t",
            information_cutoff="2026-10-01T00:00:00Z",
            origin="2026-10-01T00:00:00Z",
            hours=24,
            seed=1,
            population_n=2,
        )
        sim_holder["sim"] = fake
        await engine.step(fake)

    with pytest.raises(EngineNotConfigured):
        asyncio.run(_go())


def test_carrier_crackdown_raises_opt_outs():
    base = _run_sync(seed=21)["summary"]
    shock = _run_sync(
        seed=21,
        interventions=[
            {
                "type": "carrier_crackdown",
                "timestamp": "+5d",
                "extra": {"opt_out_multiplier": 10.0, "duration_days": 25},
            }
        ],
    )["summary"]
    assert shock["opt_outs"] > base["opt_outs"]


def test_google_enforcement_flags_excess_reviews():
    r = _run_sync(
        seed=22,
        interventions=[
            {"type": "google_enforcement", "timestamp": "+0d", "extra": {"max_reviews_per_day": 0.0}}
        ],
    )["summary"]
    assert r["reviews_flagged"] > 0
    assert r["reviews_gained"] == 0.0


def test_office_slowdown_keeps_accounting_consistent():
    r = _run_sync(
        seed=23,
        interventions=[
            {
                "type": "office_slowdown",
                "timestamp": "+0d",
                "extra": {"response_time_multiplier": 5.0, "duration_days": 30},
            }
        ],
    )["summary"]
    assert r["problems_routed"] >= r["problems_resolved"]


def test_economics_zero_text_cost_zeroes_variable_cost():
    # With free texts and no fixed fees, cost must be exactly zero and
    # revenue must equal jobs*per_job + reviews*per_review_bonus +
    # problems_resolved*per_problem_bonus.
    r = _run_sync(
        seed=24,
        pricing={
            "per_job": 1.0,
            "per_review_bonus": 2.0,
            "per_problem_bonus": 3.0,
            "text_cost": 0.0,
            "dlc_setup": 0.0,
            "dlc_monthly_fee": 0.0,
        },
    )
    s = r["summary"]
    assert s["cost"] == 0.0
    expected = s["jobs"] * 1.0 + s["reviews_gained"] * 2.0 + s["problems_resolved"] * 3.0
    assert abs(s["revenue"] - expected) < 1e-6


def test_base_case_is_profitable():
    r = _run_sync(seed=24)
    s = r["summary"]
    assert s["cost"] > 0
    assert s["revenue"] > s["cost"]


def test_speed_to_lead_mode_produces_bookings():
    r = _run_sync(seed=25, mode="speed_to_lead", simulated_days=14, leads_per_day=10)
    s = r["summary"]
    assert s["mode"] == "speed_to_lead"
    assert s["leads"] > 0
    assert s["bookings"] > 0
    assert "bookings_per_100_leads" in r["predicted_series"]


def test_speed_to_lead_coverage_beats_baseline():
    covered = _run_sync(seed=26, mode="speed_to_lead", simulated_days=14, contactable_coverage=1.0)["summary"]
    uncovered = _run_sync(seed=26, mode="speed_to_lead", simulated_days=14, contactable_coverage=0.0)[
        "summary"
    ]
    assert covered["bookings"] > uncovered["bookings"]


def test_engine_routing_for_funnel_type(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    sc = funnel_scenario("t")
    engine = get_simulation_engine(sc)
    assert engine.name == "funnelsim"


def test_engine_routing_market_unchanged(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    from marketsim.scenarios import market_scenario

    sc = market_scenario("m", ["ACME"])
    engine = get_simulation_engine(sc)
    assert engine.name == "marketsim"


def test_summary_is_projection_only():
    r = _run_sync()
    s = r["summary"]
    assert s["projection_only"] is True
    assert s["observed_t1"] is None
    assert "SIMULATED" in s["disclaimer"]
    assert s["scenario_type"] == "funnel"
    assert os.environ.get("EVE_MIRO_ENGINES") == "stub"  # sanity: suite runs offline
