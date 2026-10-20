"""Customer and office agents for the Moovloop post-job SMS loop.

Customer lifecycle: UNCONTACTED -> TEXTED -> REVIEWED | OPTED_OUT |
PROBLEM_REPORTED | SILENT, with NOT_CONTACTABLE as the terminal state for
jobs without a usable mobile number. PROBLEM_REPORTED customers are handed
to the mover's office agent, which may resolve them before they go public.

All randomness comes from caller-supplied ``random.Random`` instances so runs
are seed-deterministic. Agents never see the future.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random


class CustomerState(str, Enum):
    UNCONTACTED = "uncontacted"
    TEXTED = "texted"
    REVIEWED = "reviewed"
    OPTED_OUT = "opted_out"
    PROBLEM_REPORTED = "problem_reported"
    PROBLEM_RESOLVED = "problem_resolved"
    SILENT = "silent"  # contacted, never reviewed, never complained
    NOT_CONTACTABLE = "not_contactable"


@dataclass
class CustomerAgent:
    agent_id: str
    mover_id: str
    state: CustomerState = CustomerState.UNCONTACTED
    day_texted: int = -1
    day_terminal: int = -1
    texts_sent: int = 0
    flagged: bool = False  # review blocked by a velocity-cap intervention
    rng: Random = field(default_factory=Random)

    def contact(self, day: int, *, contactable: bool) -> int:
        """First touch: thank-you + review ask (2 texts). Returns texts sent."""
        if self.state is not CustomerState.UNCONTACTED:
            return 0
        if not contactable:
            self.state = CustomerState.NOT_CONTACTABLE
            self.day_terminal = day
            return 0
        self.state = CustomerState.TEXTED
        self.day_texted = day
        self.texts_sent += 2
        return 2

    def nudge(self) -> int:
        """Second nudge a few days later. Returns texts sent (0 if not TEXTED)."""
        if self.state is not CustomerState.TEXTED:
            return 0
        self.texts_sent += 1
        return 1

    def resolve(self, day: int, *, p_opt_out: float, p_problem: float, k_review: float) -> CustomerState:
        """Terminal draw after the nudge window.

        Outcomes are mutually exclusive, drawn from one uniform variate:
        opt-out, then problem, then review, else silent. The unconditional
        review probability among contacted customers therefore equals
        ``k_review`` exactly, matching the closed-form R = N * c * k.
        Callers must ensure p_opt_out + p_problem + k_review <= 1.
        """
        if self.state is not CustomerState.TEXTED:
            return self.state
        r = self.rng.random()
        if r < p_opt_out:
            self.state = CustomerState.OPTED_OUT
        elif r < p_opt_out + p_problem:
            self.state = CustomerState.PROBLEM_REPORTED
            self.texts_sent += 1  # office routing text
        elif r < p_opt_out + p_problem + k_review:
            self.state = CustomerState.REVIEWED
        else:
            self.state = CustomerState.SILENT
        self.day_terminal = day
        return self.state


@dataclass
class MoverOfficeAgent:
    """The mover's office: resolves reported problems with a latency draw.

    resolve_prob is the share of reported problems fixed before they go
    public. Latency is exponential with the given mean (days); the
    office_slowdown intervention scales the mean.
    """

    mover_id: str
    response_days_mean: float = 2.0
    resolve_prob: float = 0.70
    rng: Random = field(default_factory=Random)

    def attempt_resolve(self) -> tuple[bool, float]:
        """Try to resolve one reported problem.

        Returns (resolved, latency_days). Unresolved problems stay
        PROBLEM_REPORTED (terminal, assumed to go public).
        """
        if self.rng.random() >= self.resolve_prob:
            return False, 0.0
        latency = self.rng.expovariate(1.0 / max(self.response_days_mean, 0.05))
        return True, latency


@dataclass
class SpeedLead:
    """A pre-job lead for speed-to-lead mode: arrival -> response -> booking."""

    agent_id: str
    mover_id: str
    response_minutes: float = -1.0
    booked: bool = False
    covered: bool = False  # got the instant SMS response
