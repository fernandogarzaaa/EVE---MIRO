"""Unit tests for funnelsim customer and office agents."""

from __future__ import annotations

import random

from funnelsim.agents import CustomerAgent, CustomerState, MoverOfficeAgent, SpeedLead


def _cust(seed: int = 7) -> CustomerAgent:
    return CustomerAgent(agent_id="mover-00-c000001", mover_id="mover-00", rng=random.Random(seed))


def test_contact_sends_two_texts_and_marks_texted():
    c = _cust()
    assert c.contact(3, contactable=True) == 2
    assert c.state is CustomerState.TEXTED
    assert c.day_texted == 3
    assert c.texts_sent == 2


def test_contact_not_contactable_is_terminal():
    c = _cust()
    assert c.contact(0, contactable=False) == 0
    assert c.state is CustomerState.NOT_CONTACTABLE
    assert c.texts_sent == 0


def test_contact_twice_is_idempotent():
    c = _cust()
    c.contact(0, contactable=True)
    assert c.contact(1, contactable=True) == 0
    assert c.texts_sent == 2


def test_nudge_only_when_texted():
    c = _cust()
    assert c.nudge() == 0  # UNCONTACTED
    c.contact(0, contactable=True)
    assert c.nudge() == 1
    assert c.texts_sent == 3


def test_resolve_review_path_adds_no_extra_text():
    c = _cust()
    c.contact(0, contactable=True)
    c.nudge()
    # Force the review branch: k=1.0 with zero opt-out/problem mass.
    state = c.resolve(5, p_opt_out=0.0, p_problem=0.0, k_review=1.0)
    assert state is CustomerState.REVIEWED
    assert c.texts_sent == 3  # thank-you + ask + nudge


def test_resolve_opt_out_branch():
    c = _cust()
    c.contact(0, contactable=True)
    state = c.resolve(5, p_opt_out=1.0, p_problem=0.0, k_review=0.0)
    assert state is CustomerState.OPTED_OUT
    assert c.day_terminal == 5


def test_resolve_problem_branch_adds_routing_text():
    c = _cust()
    c.contact(0, contactable=True)
    c.nudge()
    state = c.resolve(5, p_opt_out=0.0, p_problem=1.0, k_review=0.0)
    assert state is CustomerState.PROBLEM_REPORTED
    assert c.texts_sent == 4  # +1 office routing text


def test_resolve_silent_branch():
    c = _cust()
    c.contact(0, contactable=True)
    state = c.resolve(5, p_opt_out=0.0, p_problem=0.0, k_review=0.0)
    assert state is CustomerState.SILENT


def test_resolve_only_from_texted():
    c = _cust()  # UNCONTACTED
    assert c.resolve(5, p_opt_out=1.0, p_problem=0.0, k_review=0.0) is CustomerState.UNCONTACTED


def test_resolve_is_statistically_fair():
    # 20k draws: review share must converge to k=0.20 within tolerance.
    n = 20000
    reviews = 0
    for i in range(n):
        c = CustomerAgent(agent_id=f"c{i}", mover_id="m", rng=random.Random(1000 + i))
        c.contact(0, contactable=True)
        if c.resolve(5, p_opt_out=0.01, p_problem=0.20, k_review=0.20) is CustomerState.REVIEWED:
            reviews += 1
    assert abs(reviews / n - 0.20) < 0.01


def test_agent_rng_is_deterministic():
    a = _cust(seed=42)
    b = _cust(seed=42)
    for agent in (a, b):
        agent.contact(0, contactable=True)
        agent.resolve(5, p_opt_out=0.05, p_problem=0.2, k_review=0.3)
    assert a.state is b.state
    assert a.texts_sent == b.texts_sent


def test_office_resolve_returns_bool_and_nonnegative_latency():
    office = MoverOfficeAgent(mover_id="m", rng=random.Random(3))
    resolved, latency = office.attempt_resolve()
    assert isinstance(resolved, bool)
    assert latency >= 0.0


def test_office_never_resolves_at_zero_prob():
    office = MoverOfficeAgent(mover_id="m", resolve_prob=0.0, rng=random.Random(3))
    for _ in range(20):
        resolved, _ = office.attempt_resolve()
        assert resolved is False


def test_speed_lead_defaults():
    lead = SpeedLead(agent_id="l1", mover_id="m")
    assert lead.response_minutes == -1.0
    assert lead.booked is False
    assert lead.covered is False
