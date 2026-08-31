"""Compare predicted trajectory vs observed. Persist Evaluation with calibration summary."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from eve_miro.core.evaluation.calibration import CalibrationSummary
from eve_miro.core.evaluation.forecasting import align_series
from eve_miro.core.evaluation.metrics import brier_score, mae, rmse, timing_error_minutes
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.temporal import utcnow


class Evaluation(BaseModel):
    id: str
    world_id: str
    simulation_id: str | None = None
    metric_name: str
    predicted: list[float] = Field(default_factory=list)
    observed: list[float] = Field(default_factory=list)
    times: list[str] = Field(default_factory=list)
    mae: float | None = None
    rmse: float | None = None
    brier: float | None = None
    timing_error_minutes: float | None = None
    calibration: CalibrationSummary = Field(default_factory=CalibrationSummary)
    predicted_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    observed_kind: ProvenanceKind = ProvenanceKind.OBSERVED
    created_at: datetime = Field(default_factory=utcnow)
    notes: str = ""
    domain_trusted: bool = True


class ReliabilityReport(BaseModel):
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    untrusted_domains: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


def reality_check(
    *,
    world_id: str,
    simulation_id: str | None,
    predicted: list[float],
    observed: list[float],
    pred_times: list[str] | None = None,
    obs_times: list[str] | None = None,
    probabilities: list[float] | None = None,
    outcomes: list[int] | None = None,
    predicted_event_minute: float | None = None,
    observed_event_minute: float | None = None,
    metric_name: str = "wind_speed_10m",
) -> Evaluation:
    if observed is None or len(observed) == 0:
        return Evaluation(
            id=f"eval_{uuid4().hex[:12]}",
            world_id=world_id,
            simulation_id=simulation_id,
            metric_name=metric_name,
            predicted=predicted,
            observed=[],
            domain_trusted=False,
            notes="No observations for this domain — do not trust it.",
            calibration=CalibrationSummary(n=0, reliability_note="No observations; do not trust this domain."),
        )
    p, o, times = predicted, observed, []
    if pred_times and obs_times:
        p, o, times = align_series(pred_times, predicted, obs_times, observed)
        if not p:
            p, o = predicted, observed
    mae_v = mae(p, o)
    rmse_v = rmse(p, o)
    brier_v = None
    if probabilities is not None and outcomes is not None:
        brier_v = brier_score(probabilities, outcomes)
    t_err = None
    if predicted_event_minute is not None and observed_event_minute is not None:
        t_err = timing_error_minutes(predicted_event_minute, observed_event_minute)
    cal = CalibrationSummary(
        n=min(len(p), len(o)),
        mae=mae_v,
        rmse=rmse_v,
        brier=brier_v,
        timing_error_minutes=t_err,
        reliability_note="Calibration is not yet established. Scenario projection, not a statement of the future.",
    )
    return Evaluation(
        id=f"eval_{uuid4().hex[:12]}",
        world_id=world_id,
        simulation_id=simulation_id,
        metric_name=metric_name,
        predicted=p,
        observed=o,
        times=times,
        mae=mae_v,
        rmse=rmse_v,
        brier=brier_v,
        timing_error_minutes=t_err,
        calibration=cal,
        notes="Predicted series is SIMULATED; observed series is OBSERVED. Kinds are never mixed.",
        domain_trusted=True,
    )


def reliability_from_freshness(
    freshness: dict[str, dict[str, Any]],
    *,
    stale_after_seconds: dict[str, float] | None = None,
) -> ReliabilityReport:
    stale_after_seconds = stale_after_seconds or {
        "openmeteo": 6 * 3600,
        "usgs": 24 * 3600,
        "opensky": 300,
        "aisstream": 300,
    }
    untrusted: list[str] = []
    sources: dict[str, dict[str, Any]] = {}
    for name, info in freshness.items():
        age = info.get("age_seconds")
        expected = stale_after_seconds.get(name, 24 * 3600)
        complete = bool(info.get("complete", True))
        stale = age is None or age > expected
        if stale or not complete or info.get("event_count", 0) == 0:
            untrusted.append(name)
            verdict = "do not trust this domain"
        else:
            verdict = "fresh"
        sources[name] = {**info, "stale": stale, "verdict": verdict}
    return ReliabilityReport(sources=sources, untrusted_domains=untrusted)
