"""Reality Ledger: prediction records with input provenance.

FORECAST-based predictions are tagged differently from OBSERVED-based.
Verdicts CORRECT / INCORRECT are computed from known numeric series (MAE).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from eve_miro.core.evaluation.metrics import mae as mae_fn
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.temporal import as_utc, utcnow

MAE_CORRECT_THRESHOLD = 1.0


class PredictionRecord(BaseModel):
    id: str
    experiment_id: str = ""
    scenario_id: str = ""
    model: str = "mirofish"
    seed: int | None = None
    cutoff: datetime
    source_versions: dict[str, str] = Field(default_factory=dict)
    input_provenance_kinds: list[str] = Field(default_factory=list)
    domain: str = "weather"
    predicted: list[float] = Field(default_factory=list)
    observed: list[float] = Field(default_factory=list)
    times: list[str] = Field(default_factory=list)
    mae: float | None = None
    verdict: Literal["CORRECT", "INCORRECT", "PENDING"] = "PENDING"
    notes: str = ""
    predicted_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    observed_kind: ProvenanceKind = ProvenanceKind.OBSERVED
    created_at: datetime = Field(default_factory=utcnow)


def classify_verdict(
    predicted: list[float],
    observed: list[float],
    *,
    threshold: float = MAE_CORRECT_THRESHOLD,
) -> tuple[str, float | None]:
    if not predicted or not observed:
        return "PENDING", None
    n = min(len(predicted), len(observed))
    err = mae_fn(predicted[:n], observed[:n])
    if err <= threshold:
        return "CORRECT", err
    return "INCORRECT", err


class RealityLedger:
    """Append-only prediction ledger. History is never mutated."""

    def __init__(self) -> None:
        self._records: list[PredictionRecord] = []

    def append(self, record: PredictionRecord) -> PredictionRecord:
        self._records.append(record)
        return record

    def record_prediction(
        self,
        *,
        experiment_id: str,
        scenario_id: str = "",
        model: str = "mirofish",
        seed: int | None = None,
        cutoff: datetime | str,
        source_versions: dict[str, str] | None = None,
        input_provenance_kinds: list[str] | None = None,
        domain: str = "weather",
        predicted: list[float] | None = None,
        observed: list[float] | None = None,
        times: list[str] | None = None,
        notes: str = "",
        threshold: float = MAE_CORRECT_THRESHOLD,
    ) -> PredictionRecord:
        predicted = list(predicted or [])
        observed = list(observed or [])
        kinds = [str(k).lower() for k in (input_provenance_kinds or [])]
        verdict, err = classify_verdict(predicted, observed, threshold=threshold)
        rec = PredictionRecord(
            id=f"pred_{uuid4().hex[:12]}",
            experiment_id=experiment_id,
            scenario_id=scenario_id,
            model=model,
            seed=seed,
            cutoff=as_utc(cutoff),
            source_versions=dict(source_versions or {}),
            input_provenance_kinds=kinds,
            domain=domain,
            predicted=predicted,
            observed=observed,
            times=list(times or []),
            mae=err,
            verdict=verdict,  # type: ignore[arg-type]
            notes=notes,
        )
        return self.append(rec)

    def list(self) -> list[PredictionRecord]:
        return list(self._records)

    def for_experiment(self, experiment_id: str) -> list[PredictionRecord]:
        return [r for r in self._records if r.experiment_id == experiment_id]
