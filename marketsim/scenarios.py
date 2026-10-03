"""Helpers to build market Scenarios programmatically.

The canonical scenario definitions live as YAML under experiments/market/.
This module is a thin builder for tests and ad-hoc runs; it uses the same
Scenario/Intervention models as every other engine.
"""

from __future__ import annotations

from typing import Any

from eve_miro.core.simulation.scenarios import Intervention, Scenario

SELL_SHOCK = "sell_shock"
VOLATILITY_SPIKE = "volatility_spike"
RATE_SHOCK = "rate_shock"


def market_scenario(
    name: str,
    symbols: list[str],
    *,
    simulated_hours: int = 48,
    population: int = 60,
    random_seed: int = 202411,
    origin: str = "2024-11-04T00:00:00Z",
    initial_prices: dict[str, float] | None = None,
    agent_mix: dict[str, float] | None = None,
    interventions: list[dict[str, Any]] | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        type="market",
        initial_world={"source": "world_state", "timestamp": origin, "region": "global"},
        duration={"simulated_hours": simulated_hours},
        agents={"population": population},
        conditions={
            "symbols": symbols,
            "initial_prices": initial_prices or {},
            "agent_mix": agent_mix or {},
        },
        interventions=[Intervention.model_validate(i) for i in (interventions or [])],
        random_seed=random_seed,
        information_cutoff=origin,
        disclaimer=(
            "SIMULATED. Agent-based scenario projections under stated assumptions, "
            "not a forecast of market prices."
        ),
    )
