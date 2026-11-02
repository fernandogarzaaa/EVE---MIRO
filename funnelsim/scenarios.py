"""Helpers to build funnel Scenarios programmatically.

The canonical scenario definitions live as YAML under experiments/funnel/.
This module is a thin builder for tests and ad-hoc runs; it uses the same
Scenario/Intervention models as every other engine.
"""

from __future__ import annotations

from typing import Any

from eve_miro.core.simulation.scenarios import Intervention, Scenario

CARRIER_CRACKDOWN = "carrier_crackdown"
GOOGLE_ENFORCEMENT = "google_enforcement"
OFFICE_SLOWDOWN = "office_slowdown"

FUNNEL_BUILDER_DISCLAIMER = (
    "SIMULATED. Scenario projection under stated assumptions, not a forecast. "
    "Customer agents are synthetic statistical personas, not real people."
)


def funnel_scenario(
    name: str,
    *,
    mode: str = "post_job",
    simulated_days: int = 90,
    movers: int = 3,
    random_seed: int = 20261016,
    origin: str = "2026-10-01T00:00:00Z",
    jobs_per_month: float = 60.0,
    contactable_coverage: float = 0.80,
    review_conversion: float = 0.20,
    opt_out_rate: float = 0.01,
    problem_rate: float = 0.20,
    problem_resolve_prob: float = 0.70,
    office_response_days_mean: float = 2.0,
    leads_per_day: float = 10.0,
    response_mean_covered_min: float = 1.0,
    response_mean_uncovered_min: float = 8.0,
    book_prob_fast: float = 0.55,
    book_prob_slow: float = 0.15,
    pricing: dict[str, Any] | None = None,
    interventions: list[dict[str, Any]] | None = None,
) -> Scenario:
    """Build a funnel Scenario.

    Parameters mirror worker-4's validated model (see
    ~/workspace/moovsoon/worker-4-simulation.md): N jobs/mo per mover,
    contactable coverage c, request-to-review conversion k, and the
    pessimistic/base/optimistic variants. ``pricing`` maps to the
    funnelsim.economics.Pricing fields; absent means engine defaults.
    """
    conditions: dict[str, Any] = {
        "mode": mode,
        "simulated_days": simulated_days,
        "jobs_per_month": jobs_per_month,
        "contactable_coverage": contactable_coverage,
        "review_conversion": review_conversion,
        "opt_out_rate": opt_out_rate,
        "problem_rate": problem_rate,
        "problem_resolve_prob": problem_resolve_prob,
        "office_response_days_mean": office_response_days_mean,
        "leads_per_day": leads_per_day,
        "response_mean_covered_min": response_mean_covered_min,
        "response_mean_uncovered_min": response_mean_uncovered_min,
        "book_prob_fast": book_prob_fast,
        "book_prob_slow": book_prob_slow,
        "pricing": pricing or {},
    }
    return Scenario(
        name=name,
        type="funnel",
        initial_world={"source": "fixture", "timestamp": origin, "region": "us"},
        duration={"simulated_days": simulated_days, "simulated_hours": simulated_days * 24},
        agents={"population": movers},
        conditions=conditions,
        interventions=[Intervention.model_validate(i) for i in (interventions or [])],
        random_seed=random_seed,
        information_cutoff=origin,
        disclaimer=FUNNEL_BUILDER_DISCLAIMER,
    )
