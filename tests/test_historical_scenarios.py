"""Tests for the historical shock scenario templates.

Covers the scenario registry (YAML directory, not a hardcoded tuple),
the new scenario-class mappings, parameter bounds grounded in the
documented source events, and the directional/shape behavior of each
template against a no-shock control at the same seed. Deterministic:
every run uses the seed from its YAML.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from eve_miro.cli.market_sim import _load_scenario_doc, list_scenarios
from eve_miro.core.orchestration.market_alignment import (
    SCENARIO_CLASSES,
    scenario_class_for,
)
from eve_miro.core.world.state import Economy, Population, WorldState
from marketsim.engine import MarketSimEngine
from marketsim.scenarios import market_scenario

NEW_SCENARIOS = (
    "earn_gap_down_001",
    "earn_gap_snapback_001",
    "sector_flash_001",
    "macro_slide_001",
)

ORIGIN = "2024-11-04T00:00:00Z"


def _series_for(stem: str, *, with_shock: bool = True) -> list[float]:
    """Run the YAML scenario (or its no-shock control) and return mids."""
    doc = _load_scenario_doc(stem)
    conditions = doc.get("conditions", {}) or {}
    symbols = [str(s) for s in conditions.get("symbols", [])]
    assert symbols, f"{stem} defines no symbols"
    sc = market_scenario(
        stem,
        symbols,
        simulated_hours=int(doc.get("duration", {}).get("simulated_hours", 120)),
        population=int((doc.get("agents", {}) or {}).get("population", 60)),
        random_seed=int(doc.get("random_seed", 202411)),
        origin=ORIGIN,
        initial_prices={
            str(k): float(v) for k, v in (conditions.get("initial_prices") or {}).items()
        },
        agent_mix=dict(conditions.get("agent_mix") or {}),
        interventions=(
            [dict(iv) for iv in doc.get("interventions", [])] if with_shock else []
        ),
    )
    world = WorldState(
        world_id=f"test-{stem}",
        timestamp=ORIGIN,
        information_cutoff=ORIGIN,
        economy=Economy(indicators={}),
    )

    async def _run():
        engine = MarketSimEngine(scenario=sc)
        sim = await engine.initialize(world, Population(synthetic_n=60))
        result = await engine.run(sim, sim.origin + timedelta(hours=sc.simulated_hours))
        return result.predicted_series[symbols[0]]

    return asyncio.run(_run())


def _returns(series: list[float]) -> list[float]:
    start = series[0]
    return [s / start - 1.0 for s in series]


# -- registry ------------------------------------------------------------

def test_scenario_class_tuples_stay_in_sync():
    """trust_profile keeps its own SCENARIO_CLASSES to avoid a circular
    import; it must mirror market_alignment's canonical tuple."""
    from eve_miro.core.orchestration import market_alignment
    from eve_miro.core.reality import trust_profile

    assert trust_profile.SCENARIO_CLASSES == market_alignment.SCENARIO_CLASSES


def test_registry_lists_all_market_yamls():
    found = list_scenarios()
    assert "sell_shock_001" in found
    assert "vol_spike_001" in found
    assert "rate_shock_001" in found
    for stem in NEW_SCENARIOS:
        assert stem in found
    # market_closed_loop.yaml is an experiment doc, not a scenario.
    assert "market_closed_loop" not in found
    assert len(found) == 7


def test_registry_rejects_unknown_scenario_fail_closed():
    from eve_miro.cli.market_sim import run_market_scenario

    with pytest.raises(ValueError, match="unknown scenario"):
        run_market_scenario("not_a_real_scenario_xyz", 72)


def test_new_scenario_classes_mapped():
    assert scenario_class_for("earn_gap_down_001") == "earn_gap_down"
    assert scenario_class_for("earn_gap_snapback_001") == "earn_gap_snapback"
    assert scenario_class_for("sector_flash_001") == "sector_flash"
    assert scenario_class_for("macro_slide_001") == "macro_slide"
    for cls in ("earn_gap_down", "earn_gap_snapback", "sector_flash", "macro_slide"):
        assert cls in SCENARIO_CLASSES
    # Old mappings unchanged.
    assert scenario_class_for("sell_shock_001") == "sell_shock"
    assert scenario_class_for("vol_spike_001") == "volatility_spike"
    assert scenario_class_for("rate_shock_001") == "rate_shock"
    assert scenario_class_for("something_unknown") == "baseline"


def test_scenario_yamls_carry_simulated_disclaimer():
    for stem in NEW_SCENARIOS:
        doc = _load_scenario_doc(stem)
        assert "SIMULATED" in str(doc.get("disclaimer", ""))
        assert doc.get("type") == "market"


# -- parameter bounds grounded in the source events ----------------------

def _interventions(stem: str) -> list[dict]:
    return [dict(iv) for iv in _load_scenario_doc(stem).get("interventions", [])]


def test_earn_gap_down_params_match_intc_event():
    ivs = _interventions("earn_gap_down_001")
    sells = [iv for iv in ivs if iv["type"] == "sell_shock"]
    rates = [iv for iv in ivs if iv["type"] == "rate_shock"]
    # Sustained liquidation: at least one long pressure leg (>= 24h).
    assert any(int(s["extra"]["duration_hours"]) >= 24 for s in sells)
    # Permanent impairment in the documented -20% to -30% band (INTC -26.06%).
    assert len(rates) == 1
    fv = float(rates[0]["extra"]["fair_value_pct_change"])
    assert -0.30 <= fv <= -0.20


def test_earn_gap_snapback_params_match_panw_event():
    ivs = _interventions("earn_gap_snapback_001")
    sells = [iv for iv in ivs if iv["type"] == "sell_shock"]
    rates = [iv for iv in ivs if iv["type"] == "rate_shock"]
    # Sharp pressure like the -28.44% day, but fundamentals intact: no
    # fair-value impairment, so dip-buying can drive the V-recovery.
    assert sells, "expected liquidation pressure"
    assert not rates, "snapback template must not impair fair value"
    assert any(int(s["extra"]["duration_hours"]) <= 12 for s in sells)


def test_sector_flash_params_match_nvda_event():
    ivs = _interventions("sector_flash_001")
    sells = [iv for iv in ivs if iv["type"] == "sell_shock"]
    rates = [iv for iv in ivs if iv["type"] == "rate_shock"]
    # One-session flash: short, intense, no lasting impairment.
    assert sells and all(int(s["extra"]["duration_hours"]) <= 8 for s in sells)
    assert not rates


def test_macro_slide_params_match_spy_event():
    ivs = _interventions("macro_slide_001")
    sells = [iv for iv in ivs if iv["type"] == "sell_shock"]
    rates = [iv for iv in ivs if iv["type"] == "rate_shock"]
    # Two escalating waves about a session apart (SPY -4.93% then -5.85%).
    assert len(sells) >= 2
    # Mild lasting impairment: tariffs as a small tax on growth.
    assert len(rates) == 1
    fv = float(rates[0]["extra"]["fair_value_pct_change"])
    assert -0.15 <= fv <= -0.03


# -- directional / shape behavior vs control ------------------------------

def test_earn_gap_down_sustained_no_recovery():
    rets = _returns(_series_for("earn_gap_down_001"))
    ctrl = _returns(_series_for("earn_gap_down_001", with_shock=False))
    assert min(rets) <= -0.10, "shock must draw down materially"
    assert min(rets) < min(ctrl) - 0.05, "shock must beat the control down"
    assert rets[-1] <= -0.05, "impaired template must not recover"


def test_earn_gap_snapback_recovers():
    rets = _returns(_series_for("earn_gap_snapback_001"))
    trough = min(rets)
    assert trough <= -0.03, "shock must dip first"
    recovered = rets[-1] - trough
    assert recovered >= 0.5 * abs(trough), "intact fundamentals must retrace the drop"


def test_sector_flash_dips_then_recovers_fast():
    rets = _returns(_series_for("sector_flash_001"))
    first_day = rets[:30]
    trough = min(first_day)
    assert trough <= -0.03, "flash must print its low inside the first session"
    later = rets[48:72]
    assert max(later) >= trough + 0.5 * abs(trough), "flash must snap back"


def test_macro_slide_grinds_lower_without_v():
    rets = _returns(_series_for("macro_slide_001"))
    ctrl = _returns(_series_for("macro_slide_001", with_shock=False))
    assert min(rets) <= -0.08, "two-wave slide must draw down materially"
    assert min(rets) < min(ctrl) - 0.05
    first_half_low = min(rets[:48])
    second_half_low = min(rets[48:])
    assert second_half_low < first_half_low, "second wave must extend the slide"
    assert rets[-1] <= -0.05, "no V-recovery inside the horizon"
