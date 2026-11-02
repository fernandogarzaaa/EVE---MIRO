"""Unit economics for the Moovloop post-job SMS loop.

Parameter VALUES live in datasets/fixtures/funnel_baseline.json (with
provenance) and flow in through scenario conditions. This module holds
only the arithmetic, so tests can vary the inputs. All figures below are
documented in ~/workspace/moovsoon/worker-4-simulation.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pricing:
    per_job: float = 0.80  # base unit: per job processed (ASSUMPTION, v3 pricing)
    per_review_bonus: float = 5.00  # outcome bonus per incremental review
    per_problem_bonus: float = 10.00  # outcome bonus per problem resolved pre-public
    per_booking_bonus: float = 25.00  # speed-to-lead mode only (ASSUMPTION)
    text_cost: float = 0.013  # all-in upper bound (Twilio base + carrier surcharge)
    dlc_setup: float = 19.50  # $4.50 brand + $15 campaign, amortized over 12 months
    dlc_monthly_fee: float = 2.00  # sole-prop tier
    dlc_amort_months: int = 12


def monthly_fixed_cost(p: Pricing) -> float:
    """10DLC registration amortized plus the monthly campaign fee, per mover."""
    return p.dlc_setup / max(p.dlc_amort_months, 1) + p.dlc_monthly_fee


def loop_variable_cost(texts_sent: int, p: Pricing) -> float:
    """Variable SMS cost for one customer loop."""
    return texts_sent * p.text_cost


def expected_texts_per_loop(problem_rate: float = 0.20) -> float:
    """3.2 texts: thank-you + ask + nudge, plus problem-routing at problem_rate."""
    return 3.0 + problem_rate
