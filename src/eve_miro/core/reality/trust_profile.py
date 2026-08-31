"""TrustProfile per domain (weather, mobility, population, news).

Richer than GET /reliability. Low scores recommend DO_NOT_USE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from eve_miro.core.world.temporal import utcnow

DOMAINS = ("weather", "mobility", "population", "news")
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
