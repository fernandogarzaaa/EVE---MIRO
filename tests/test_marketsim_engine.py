"""End-to-end tests for MarketSimEngine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eve_miro.core.simulation.engine import Simulation, get_simulation_engine
from eve_miro.core.simulation.scenarios import Scenario
from eve_miro.core.world.state import Economy, Population, WorldState
from eve_miro.errors import EngineNotConfigured
from marketsim.engine import MarketSimEngine, read_market_slice
from marketsim.scenarios import RATE_SHOCK, SELL_SHOCK, VOLATILITY_SPIKE, market_scenario


def _world(tickers: dict | None = None) -> WorldState:
    # Phase 1 canonical shape: Economy.indicators["market_snapshot"]["tickers"],
    # each ticker like {"latest_close": float, "realized_vol_5d": float, ...}.
    indicators = {"market_snapshot": {"tickers": tickers}} if tickers is not None else {}
    return WorldState(
        world_id="w_test",
        timestamp="2024-11-04T00:00:00Z",
        information_cutoff="2024-11-04T00:00:00Z",
        economy=Economy(indicators=indicators),
    )


def _pop(n: int = 40) -> Population:
    return Population(synthetic_n=n)


async def _run(engine: MarketSimEngine, world: WorldState, pop: Population, hours: int):
    sim = await engine.initialize(world, pop)
    until = sim.origin.replace(tzinfo=timezone.utc) + __import__("datetime").timedelta(hours=hours)
    return await engine.run(sim, until)


def test_read_market_slice_extracts_prices():
    world = _world(
        {
            "ACME": {"latest_close": 100.0, "realized_vol_5d": 0.02, "realized_vol_20d": 0.03},
            "JUNK": {"nope": 1},
        }
    )
    out = read_market_slice(world)
    assert out["ACME"]["price"] == 100.0
    assert out["ACME"]["realized_vol"] == {"5d": 0.02, "20d": 0.03}
    assert "JUNK" not in out


def test_read_market_slice_absent_is_empty():
    assert read_market_slice(_world(None)) == {}
    assert read_market_slice(_world({"ACME": {"latest_close": None}})) == {}


@pytest.mark.asyncio
async def test_initialize_uses_world_slice_and_scenario():
    sc = market_scenario("t1", ["ACME", "BETA"], population=20, simulated_hours=6)
    engine = MarketSimEngine(scenario=sc)
    sim = await engine.initialize(_world({"ACME": {"latest_close": 120.0}}), _pop(20))
    assert sim.scenario_type == "market"
    assert sim.population_n == 20
    state = engine._states[sim.id]
    assert set(state.instruments) == {"ACME", "BETA"}
    assert state.instruments["ACME"].mid_history[0] == 120.0  # world slice wins
    assert state.instruments["BETA"].mid_history[0] == 100.0  # default fallback


@pytest.mark.asyncio
async def test_initialize_scenario_only_without_world_slice():
    sc = market_scenario("t2", ["ACME"], population=10, simulated_hours=4,
                         initial_prices={"ACME": 55.0})
    engine = MarketSimEngine(scenario=sc)
    sim = await engine.initialize(_world(None), _pop(10))
    assert engine._states[sim.id].instruments["ACME"].mid_history[0] == 55.0


@pytest.mark.asyncio
async def test_initialize_raises_without_instruments():
    engine = MarketSimEngine(scenario=None)
    with pytest.raises(EngineNotConfigured, match="no instruments"):
        await engine.initialize(_world(None), _pop(10))


@pytest.mark.asyncio
async def test_step_unknown_simulation_raises():
    engine = MarketSimEngine()
    sim = Simulation(
        id="nope", world_id="w", scenario_name="x",
        information_cutoff=datetime(2024, 11, 4, tzinfo=timezone.utc),
        origin=datetime(2024, 11, 4, tzinfo=timezone.utc),
        hours=2, seed=1, population_n=0, scenario_type="market",
    )
    with pytest.raises(EngineNotConfigured, match="initialize first"):
        await engine.step(sim)


@pytest.mark.asyncio
async def test_run_produces_per_symbol_series():
    sc = market_scenario("t3", ["ACME", "BETA"], population=30, simulated_hours=12)
    engine = MarketSimEngine(scenario=sc)
    result = await _run(engine, _world(None), _pop(30), 12)
    assert set(result.predicted_series) == {"ACME", "BETA"}
    assert len(result.predicted_series["ACME"]) == 12
    assert len(result.predicted_times) == 12
    assert result.summary["scenario_type"] == "market"
    assert result.summary["provenance_kind"] == "simulated"
    assert result.simulation.status == "completed"
    assert all(p > 0 for p in result.predicted_series["ACME"])


@pytest.mark.asyncio
async def test_run_is_seed_deterministic():
    async def series():
        sc = market_scenario("t4", ["ACME"], population=30, simulated_hours=12, random_seed=777)
        engine = MarketSimEngine(scenario=sc)
        result = await _run(engine, _world(None), _pop(30), 12)
        return result.predicted_series["ACME"]

    assert await series() == await series()


@pytest.mark.asyncio
async def test_sell_shock_depresses_shocked_ticker_vs_control():
    base = dict(name="shock", symbols=["ACME"], population=60, simulated_hours=48,
                initial_prices={"ACME": 100.0}, random_seed=202411)
    shock = market_scenario(
        **base,
        interventions=[{"type": SELL_SHOCK, "timestamp": "+12h",
                        "extra": {"symbol": "ACME", "quantity": 20000.0, "duration_hours": 4}}],
    )
    control = market_scenario(**{**base, "name": "control"})
    shock_res = await _run(MarketSimEngine(scenario=shock), _world(None), _pop(60), 48)
    ctrl_res = await _run(MarketSimEngine(scenario=control), _world(None), _pop(60), 48)
    s = shock_res.predicted_series["ACME"]
    c = ctrl_res.predicted_series["ACME"]
    # The shock must leave a mark: trough after the shock is deeper than control's.
    assert min(s[12:24]) < min(c[12:24])


@pytest.mark.asyncio
async def test_vol_spike_raises_realized_range():
    base = dict(name="vol", symbols=["ACME"], population=60, simulated_hours=48,
                initial_prices={"ACME": 100.0}, random_seed=202411)
    spike = market_scenario(
        **base,
        interventions=[{"type": VOLATILITY_SPIKE, "timestamp": "+6h",
                        "extra": {"symbol": "ACME", "multiplier": 8.0, "duration_hours": 12}}],
    )
    control = market_scenario(**{**base, "name": "control"})
    spike_res = await _run(MarketSimEngine(scenario=spike), _world(None), _pop(60), 48)
    ctrl_res = await _run(MarketSimEngine(scenario=control), _world(None), _pop(60), 48)

    def window_range(series, lo, hi):
        w = series[lo:hi]
        return max(w) - min(w)

    s = spike_res.predicted_series["ACME"]
    c = ctrl_res.predicted_series["ACME"]
    assert window_range(s, 6, 18) > window_range(c, 6, 18)


@pytest.mark.asyncio
async def test_rate_shock_shifts_fair_value_and_price():
    base = dict(name="rate", symbols=["ACME"], population=60, simulated_hours=48,
                initial_prices={"ACME": 100.0}, random_seed=202411)
    shocked = market_scenario(
        **base,
        interventions=[{"type": RATE_SHOCK, "timestamp": "+6h",
                        "extra": {"fair_value_pct_change": -0.10}}],
    )
    control = market_scenario(**{**base, "name": "control"})
    engine_s = MarketSimEngine(scenario=shocked)
    res_s = await _run(engine_s, _world(None), _pop(60), 48)
    res_c = await _run(MarketSimEngine(scenario=control), _world(None), _pop(60), 48)
    assert res_s.summary["symbols"]["ACME"]["final_fair_value"] == pytest.approx(90.0)
    assert res_c.summary["symbols"]["ACME"]["final_fair_value"] == pytest.approx(100.0)
    # Fundamental traders drag the price down toward the new anchor.
    assert res_s.predicted_series["ACME"][-1] < res_c.predicted_series["ACME"][-1]


def test_factory_routes_market_scenario_to_marketsim(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    sc = market_scenario("f1", ["ACME"])
    engine = get_simulation_engine(sc)
    assert engine.name == "marketsim"


def test_factory_keeps_mirofish_for_non_market(monkeypatch):
    monkeypatch.setenv("EVE_MIRO_ENGINES", "in-tree")
    sc = Scenario(
        name="ty", type="typhoon", initial_world={"timestamp": "2024-11-04T00:00:00Z"},
        duration={"simulated_hours": 2}, agents={"population": 4},
        information_cutoff="2024-11-04T00:00:00Z",
    )
    engine = get_simulation_engine(sc)
    assert engine.name == "mirofish"


def test_factory_stub_mode_unchanged():
    # conftest forces EVE_MIRO_ENGINES=stub; factory must still return the stub.
    engine = get_simulation_engine(market_scenario("f2", ["ACME"]))
    assert engine.name == "stub"
