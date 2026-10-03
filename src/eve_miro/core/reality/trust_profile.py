"""TrustProfile per domain (weather, mobility, population, news).

Richer than GET /reliability. Low scores recommend DO_NOT_USE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from eve_miro.core.world.temporal import utcnow

DOMAINS = ("weather", "mobility", "population", "news")
SCENARIO_CLASSES = ("sell_shock", "volatility_spike", "rate_shock", "baseline")
DO_NOT_USE_BELOW = 0.40
CAUTION_BELOW = 0.70


class DomainTrust(BaseModel):
    domain: str
    score: float
    recommendation: Literal["USE", "CAUTION", "DO_NOT_USE"]
    mae: float | None = None
    n: int = 0
    notes: str = ""


class TrustProfile(BaseModel):
    domains: dict[str, DomainTrust] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utcnow)
    experiment_id: str | None = None
    notes: str = "Trust is computed from ledger MAE / coverage. Not an LLM score."

    def recommendation_for(self, domain: str) -> str:
        row = self.domains.get(domain)
        return row.recommendation if row else "DO_NOT_USE"


def _recommendation(score: float) -> Literal["USE", "CAUTION", "DO_NOT_USE"]:
    if score < DO_NOT_USE_BELOW:
        return "DO_NOT_USE"
    if score < CAUTION_BELOW:
        return "CAUTION"
    return "USE"


def score_from_mae(mae: float | None, n: int) -> float:
    if n <= 0 or mae is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 / (1.0 + float(mae) / 10.0)))


def trust_profile_from_ledger(
    records: list[Any],
    *,
    experiment_id: str | None = None,
) -> TrustProfile:
    by_domain: dict[str, list[Any]] = {d: [] for d in DOMAINS}
    for rec in records:
        domain = getattr(rec, "domain", None) or (rec.get("domain") if isinstance(rec, dict) else "weather")
        by_domain.setdefault(str(domain), []).append(rec)

    domains: dict[str, DomainTrust] = {}
    for domain in DOMAINS:
        rows = by_domain.get(domain) or []
        maes = []
        n_obs = 0
        for r in rows:
            mae = getattr(r, "mae", None) if not isinstance(r, dict) else r.get("mae")
            observed = getattr(r, "observed", None) if not isinstance(r, dict) else r.get("observed")
            if mae is not None:
                maes.append(float(mae))
            if observed:
                n_obs += len(observed)
        mean_mae = (sum(maes) / len(maes)) if maes else None
        n = n_obs if n_obs else len(rows)
        score = score_from_mae(mean_mae, n if maes else 0)
        recs = _recommendation(score)
        note = "no observations; do not trust this domain" if not maes else f"mean_mae={mean_mae:.4f}" if mean_mae is not None else ""
        if recs == "DO_NOT_USE" and not note:
            note = "score below threshold — DO_NOT_USE"
        domains[domain] = DomainTrust(
            domain=domain,
            score=round(score, 4),
            recommendation=recs,
            mae=mean_mae,
            n=n,
            notes=note,
        )
    return TrustProfile(domains=domains, experiment_id=experiment_id)


class ScenarioTrust(BaseModel):
    """Calibration of one market scenario class over past alignments.

    Answers: for scenario class X, over N past alignments, the sim's
    drawdown predictions were within `drawdown_tolerance` of observed
    `drawdown_within_tol_frac` of the time.
    """

    scenario_class: str
    n_alignments: int = 0
    drawdown_tolerance: float = 0.02
    drawdown_within_tol_frac: float = 0.0
    mean_drawdown_error: float | None = None
    mean_ks_statistic: float | None = None
    score: float = 0.0
    recommendation: Literal["USE", "CAUTION", "DO_NOT_USE"] = "DO_NOT_USE"
    notes: str = ""

    def describe(self) -> str:
        within = int(round(self.drawdown_within_tol_frac * self.n_alignments))
        return (
            f"for scenario class {self.scenario_class}, over {self.n_alignments} "
            f"past alignments, the sim's drawdown predictions were within "
            f"{self.drawdown_tolerance:.2%} of observed "
            f"{self.drawdown_within_tol_frac:.0%} of the time "
            f"({within} of {self.n_alignments})."
        )


def _rec_field(rec: Any, name: str) -> Any:
    if isinstance(rec, dict):
        return rec.get(name)
    return getattr(rec, name, None)


def scenario_trust_from_ledger(
    records: list[Any],
    *,
    drawdown_tolerance: float = 0.02,
) -> dict[str, ScenarioTrust]:
    """Per-scenario-class calibration from market-domain ledger records."""
    by_class: dict[str, list[Any]] = {}
    for rec in records:
        if _rec_field(rec, "domain") != "market":
            continue
        sclass = str(_rec_field(rec, "scenario_class") or "baseline")
        by_class.setdefault(sclass, []).append(rec)

    out: dict[str, ScenarioTrust] = {}
    for sclass in SCENARIO_CLASSES:
        rows = by_class.get(sclass) or []
        dd_errors: list[float] = []
        ks_stats: list[float] = []
        within = 0
        for r in rows:
            metrics = _rec_field(r, "metrics") or {}
            dd_err = metrics.get("drawdown_error") if isinstance(metrics, dict) else None
            ks_stat = metrics.get("ks_statistic") if isinstance(metrics, dict) else None
            if dd_err is not None:
                dd_errors.append(float(dd_err))
                if float(dd_err) <= drawdown_tolerance:
                    within += 1
            if ks_stat is not None:
                ks_stats.append(float(ks_stat))
        n = len(rows)
        frac = (within / n) if n else 0.0
        mean_dd = (sum(dd_errors) / len(dd_errors)) if dd_errors else None
        mean_ks = (sum(ks_stats) / len(ks_stats)) if ks_stats else None
        score = round(0.6 * frac + 0.4 * (1.0 - (mean_ks if mean_ks is not None else 1.0)), 4)
        rec = _recommendation(score)
        if n == 0:
            note = "no alignments recorded for this scenario class; do not trust it"
        else:
            note = (
                f"n={n}, drawdown within {drawdown_tolerance:.2%}: "
                f"{within}/{n} ({frac:.0%})"
            )
            if mean_dd is not None:
                note += f", mean_drawdown_error={mean_dd:.4f}"
        out[sclass] = ScenarioTrust(
            scenario_class=sclass,
            n_alignments=n,
            drawdown_tolerance=drawdown_tolerance,
            drawdown_within_tol_frac=round(frac, 4),
            mean_drawdown_error=round(mean_dd, 6) if mean_dd is not None else None,
            mean_ks_statistic=round(mean_ks, 6) if mean_ks is not None else None,
            score=score,
            recommendation=rec,
            notes=note,
        )
    return out
