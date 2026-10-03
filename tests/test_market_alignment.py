"""Phase 3: market alignment metrics, ledger tagging, scenario-class trust.

All synthetic and offline. No network.
"""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest

from eve_miro.core.orchestration.market_alignment import (
    align_market,
    ks_2samp,
    log_returns,
    max_drawdown,
    observed_price_series,
    record_market_alignment,
    rolling_vol,
    scenario_class_for,
)
from eve_miro.core.reality.ledger import RealityLedger
from eve_miro.core.reality.trust_profile import scenario_trust_from_ledger
from eve_miro.core.world.events import ProvenanceKind
from tests.helpers import make_event, utc


def _bars(ticker: str, start: str, closes: list[float], interval: str = "1d"):
    t0 = utc(start)
    events = []
    for i, close in enumerate(closes):
        t = t0 + timedelta(days=i if interval == "1d" else 0,
                           hours=i if interval != "1d" else 0)
        events.append(
            make_event(
                f"bar-{ticker}-{i}",
                t.isoformat().replace("+00:00", "Z"),
                event_type="market.bar",
                payload={"ticker": ticker, "close": close, "interval": interval},
                provider="test",
            )
        )
    return events


def _obs(rows: list[tuple[str, float]]) -> dict[str, list[tuple[str, float]]]:
    return {"ACME": rows}


# -- pure metric units -------------------------------------------------------

def test_ks_identical_is_zero():
    a = [0.01, -0.02, 0.015, -0.005, 0.03]
    stat, p = ks_2samp(a, list(a))
    assert stat == 0.0
    assert p == 1.0


def test_ks_shifted_is_positive():
    a = [0.001 * i for i in range(50)]
    b = [x + 0.05 for x in a]
    stat, p = ks_2samp(a, b)
    assert stat > 0.5
    assert 0.0 <= p <= 1.0


def test_ks_empty_raises():
    with pytest.raises(ValueError):
        ks_2samp([], [1.0])


def test_max_drawdown_known_values():
    assert max_drawdown([100.0, 120.0, 90.0, 95.0]) == pytest.approx(-0.25)
    assert max_drawdown([100.0, 101.0, 102.0]) == 0.0
    assert max_drawdown([]) == 0.0


def test_rolling_vol_flat_series_zero():
    vols = rolling_vol([100.0] * 10)
    assert all(v == 0.0 for v in vols)
    assert len(vols) == 10


def test_log_returns_known():
    assert log_returns([100.0, 110.0]) == pytest.approx([0.0953102], rel=1e-4)
    assert log_returns([100.0]) == []


# -- scenario class mapping --------------------------------------------------

def test_scenario_class_for():
    assert scenario_class_for("market_sell_shock_001") == "sell_shock"
    assert scenario_class_for("vol_spike_001") == "volatility_spike"
    assert scenario_class_for("x_volatility_spike_y") == "volatility_spike"
    assert scenario_class_for("rate_shock_001") == "rate_shock"
    assert scenario_class_for("baseline") == "baseline"
    assert scenario_class_for("something_else") == "baseline"
    assert scenario_class_for("") == "baseline"


# -- observed series extraction ----------------------------------------------

def test_observed_price_series_sorts_and_filters():
    events = _bars("ACME", "2024-11-05T00:00:00Z", [103.0, 101.0, 102.0])
    # out-of-order insert: extraction must sort by effective time
    events = [events[2], events[0], events[1]]
    # non-bar and SIMULATED events are ignored
    events.append(make_event("n1", "2024-11-05T00:00:00Z",
                             event_type="market.news", payload={"title": "x"}))
    events.append(make_event("s1", "2024-11-05T00:00:00Z", kind=ProvenanceKind.SIMULATED,
                             event_type="market.bar",
                             payload={"ticker": "ACME", "close": 999.0}))
    rows = observed_price_series(events)
    assert list(rows) == ["ACME"]
    assert [c for _, c in rows["ACME"]] == [103.0, 101.0, 102.0]


# -- align_market ------------------------------------------------------------

def _series(prices):
    return [(f"t{i}", p) for i, p in enumerate(prices)]


def test_align_market_identical_scores_one():
    prices = [100.0 + i * 0.5 - (i % 3) for i in range(30)]
    al = align_market(scenario_id="sell_shock_001",
                      predicted={"ACME": prices},
                      observed=_obs(_series(prices)),
                      n_seeds=2)
    assert al.scenario_class == "sell_shock"
    assert al.aggregate_score == 1.0
    sym = al.symbols["ACME"]
    assert sym.ks_statistic == 0.0
    assert sym.drawdown_error == 0.0
    assert sym.symbol_score == 1.0
    assert al.skipped_symbols == []


def test_align_market_shifted_scores_worse_monotonic():
    import random

    base = [100.0 + 0.3 * i + (1 if i % 4 == 0 else 0) for i in range(40)]
    obs = _obs(_series(base))
    rng = random.Random(42)
    mild = [p + rng.gauss(0, 0.2) for p in base]
    wild = [p + rng.gauss(0, 2.0) for p in base]
    s_mild = align_market(scenario_id="vol_spike_001",
                          predicted={"ACME": mild}, observed=obs).aggregate_score
    s_wild = align_market(scenario_id="vol_spike_001",
                          predicted={"ACME": wild}, observed=obs).aggregate_score
    assert 0.0 <= s_wild < s_mild < 1.0


def test_align_market_missing_symbol_skipped():
    al = align_market(scenario_id="rate_shock_001",
                      predicted={"ACME": [100.0, 101.0, 102.0, 103.0]},
                      observed=_obs(_series([100.0, 101.0, 102.0, 103.0])))
    # BETA observed but not predicted: skipped, not an error
    al2 = align_market(scenario_id="rate_shock_001",
                       predicted={"ACME": [100.0, 101.0, 102.0, 103.0]},
                       observed={"ACME": _series([100.0, 101.0, 102.0, 103.0]),
                                 "BETA": _series([50.0, 51.0, 52.0, 53.0])})
    assert al.aggregate_score == 1.0
    assert "BETA" in al2.skipped_symbols
    assert "ACME" in al2.symbols


# -- ledger recording --------------------------------------------------------

def test_record_market_alignment_tags_ledger():
    ledger = RealityLedger()
    prices = [100.0 + i * 0.2 for i in range(20)]
    alignment, ids, evals = record_market_alignment(
        ledger,
        experiment_id="exp1",
        scenario_id="sell_shock_001",
        engine_name="marketsim",
        seed=7,
        predicted={"ACME": prices},
        observed=_obs(_series([p * 0.99 for p in prices])),
        cutoff="2024-11-04T00:00:00Z",
        source_versions={"test": "fixture"},
        input_kinds=["observed"],
        n_seeds=2,
    )
    assert alignment.scenario_class == "sell_shock"
    assert len(ids) == 1
    rec = ledger.list()[0]
    assert rec.domain == "market"
    assert rec.scenario_class == "sell_shock"
    assert rec.model == "marketsim"
    assert set(rec.metrics) == {"ks_statistic", "ks_pvalue", "return_mae",
                                "vol_path_mae", "drawdown_error", "symbol_score"}
    assert evals[0]["metric_name"] == "market:ACME"
    assert evals[0]["scenario_class"] == "sell_shock"


# -- scenario trust ----------------------------------------------------------

def _trust_record(sclass, dd_error, ks):
    ledger = RealityLedger()
    return ledger.record_prediction(
        experiment_id="exp1",
        scenario_id=f"x_{sclass}",
        scenario_class=sclass,
        model="marketsim",
        cutoff="2024-11-04T00:00:00Z",
        domain="market",
        predicted=[100.0, 101.0],
        observed=[100.0, 101.5],
        metrics={"drawdown_error": dd_error, "ks_statistic": ks},
    )


def test_scenario_trust_from_ledger_answers_calibration_question():
    records = [
        _trust_record("sell_shock", 0.005, 0.10),
        _trust_record("sell_shock", 0.010, 0.12),
        _trust_record("sell_shock", 0.030, 0.20),
        _trust_record("sell_shock", 0.050, 0.25),
    ]
    trust = scenario_trust_from_ledger(records, drawdown_tolerance=0.02)
    st = trust["sell_shock"]
    assert st.n_alignments == 4
    assert st.drawdown_within_tol_frac == 0.5
    assert st.mean_drawdown_error == pytest.approx(0.02375)
    text = st.describe()
    assert "sell_shock" in text and "2 of 4" in text and "50%" in text


def test_scenario_trust_empty_class_is_do_not_use():
    trust = scenario_trust_from_ledger([], drawdown_tolerance=0.02)
    st = trust["rate_shock"]
    assert st.n_alignments == 0
    assert st.recommendation == "DO_NOT_USE"
    assert "no alignments" in st.notes


# -- end to end: marketsim scenario, fake observed t1 ------------------------

def _e2e_world():
    from eve_miro.core.world.state import Economy, Population, WorldState
    return (
        WorldState(
            world_id="w_e2e",
            timestamp="2024-11-04T00:00:00Z",
            information_cutoff="2024-11-04T00:00:00Z",
            economy=Economy(indicators={}),
        ),
        Population(synthetic_n=12),
    )


async def _e2e_run(seed: int, shock_qty: float):
    from marketsim.engine import MarketSimEngine
    from marketsim.scenarios import market_scenario

    symbols = ["ACME", "BETA"]
    sc = market_scenario(
        f"sell_shock_e2e_{seed}",
        symbols,
        population=12,
        simulated_hours=12,
        random_seed=seed,
        initial_prices={"ACME": 100.0, "BETA": 50.0},
        interventions=[
            {
                "type": "sell_shock",
                "timestamp": "+6h",
                "extra": {"symbol": "ACME", "quantity": shock_qty,
                           "duration_hours": 2},
            }
        ],
    )
    engine = MarketSimEngine(scenario=sc)
    world, pop = _e2e_world()
    sim = await engine.initialize(world, pop)
    until = sim.origin.replace(tzinfo=timezone.utc) + timedelta(hours=12)
    return await engine.run(sim, until)


@pytest.mark.asyncio
async def test_end_to_end_marketsim_alignment_sane():
    run_a = await _e2e_run(seed=7, shock_qty=20000.0)
    run_b = await _e2e_run(seed=8, shock_qty=5000.0)
    assert set(run_a.predicted_series) == {"ACME", "BETA"}

    # Fake "observed" t1: run B's ACME series as market.bar events.
    b_acme = run_b.predicted_series["ACME"]
    t0 = utc("2024-11-04T01:00:00Z")
    events = []
    for i, close in enumerate(b_acme):
        t = t0 + timedelta(hours=i)
        events.append(
            make_event(
                f"obs-{i}", t.isoformat().replace("+00:00", "Z"),
                event_type="market.bar",
                payload={"ticker": "ACME", "close": close, "interval": "1h"},
            )
        )
    observed = observed_price_series(events)

    same = align_market(scenario_id="sell_shock_e2e",
                        predicted={"ACME": b_acme}, observed=observed)
    assert same.aggregate_score == 1.0

    diff = align_market(scenario_id="sell_shock_e2e",
                        predicted={"ACME": run_a.predicted_series["ACME"]},
                        observed=observed)
    assert 0.0 <= diff.aggregate_score < 1.0
    # the shocked symbol shows a drawdown error against the milder run
    assert diff.symbols["ACME"].drawdown_error >= 0.0


# -- closed loop wiring ------------------------------------------------------

@pytest.mark.asyncio
async def test_closed_loop_market_wiring(monkeypatch):
    from pathlib import Path

    from eve_miro.core.orchestration.closed_loop import ClosedLoop
    from eve_miro.core.orchestration.experiment import load_experiment
    from eve_miro.storage.event_store import InMemoryEventStore
    from marketsim.engine import MarketSimEngine

    monkeypatch.setattr(
        "eve_miro.core.orchestration.closed_loop.get_simulation_engine",
        lambda scenario, artifacts=None: MarketSimEngine(scenario=scenario),
    )
    yaml_path = (
        Path(__file__).parent.parent / "experiments" / "market" / "market_closed_loop.yaml"
    )
    spec = load_experiment(yaml_path)
    assert spec.experiment.simulation.engine == "marketsim"

    closes_t0 = [100.0 + 0.1 * i for i in range(16)]
    t0 = _bars("ACME", "2024-10-20T00:00:00Z", closes_t0, interval="1d")
    closes_t1 = [102.0 - 0.05 * i for i in range(12)]
    t1 = _bars("ACME", "2024-11-04T01:00:00Z", closes_t1, interval="1h")

    result = await ClosedLoop().run(
        spec, InMemoryEventStore(), t0, t1,
        agents=12, seeds=[7, 8], horizon_hours=12, world_id="w_mkt",
    )
    assert result.market_alignments, "market branch must produce alignments"
    al = result.market_alignments[0]
    assert al.scenario_class == "sell_shock"
    assert "ACME" in al.symbols
    assert 0.0 <= al.aggregate_score <= 1.0

    market_recs = [r for r in result.ledger_record_ids]
    assert market_recs
    assert result.scenario_trust is not None
    assert result.scenario_trust["sell_shock"].n_alignments >= 1
    assert any(e["metric_name"] == "market:ACME" for e in result.evaluations)
