"""Compare predicted trajectory vs observed. Persist Evaluation with calibration summary."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from eve_miro.core.evaluation.calibration import CalibrationSummary
from eve_miro.core.evaluation.confidence import source_confidence_from_fields
from eve_miro.core.evaluation.forecasting import align_series
from eve_miro.core.evaluation.metrics import (
    brier_score,
    ece,
    ece_bins,
    geographic_distance_km,
    iou,
    log_loss,
    mae,
    mape,
    rmse,
    timing_error_minutes,
    track_divergence,
)
from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.provenance import ProvenanceGraph, conclusion_graph
from eve_miro.core.world.temporal import utcnow

# Re-export so callers can import source_confidence from this module too.
from eve_miro.core.evaluation.confidence import source_confidence  # noqa: F401


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
    mape: float | None = None
    brier: float | None = None
    log_loss: float | None = None
    ece: float | None = None
    timing_error_minutes: float | None = None
    geographic_distance_km: float | None = None
    iou: float | None = None
    track_divergence: float | None = None
    bundle: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    calibration: CalibrationSummary = Field(default_factory=CalibrationSummary)
    predicted_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    observed_kind: ProvenanceKind = ProvenanceKind.OBSERVED
    created_at: datetime = Field(default_factory=utcnow)
    notes: str = ""
    domain_trusted: bool = True
    episode_id: str | None = None
    world_state_timestamp: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    source_providers: list[str] = Field(default_factory=list)
    provenance_graph: ProvenanceGraph | None = None

    def trace(self) -> list[Any]:
        """Why this evaluation: conclusion → simulation/state → events → sources."""
        if self.provenance_graph is None:
            return []
        return self.provenance_graph.trace(self.id)


class ReliabilityReport(BaseModel):
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)
    untrusted_domains: list[str] = Field(default_factory=list)
    source_confidence: dict[str, float] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utcnow)


def _safe_mape(predicted: list[float], observed: list[float]) -> float | None:
    try:
        return mape(predicted, observed)
    except ValueError:
        return None


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
    pred_coords: tuple[float, float] | None = None,
    obs_coords: tuple[float, float] | None = None,
    pred_track: list[tuple[float, float]] | None = None,
    obs_track: list[tuple[float, float]] | None = None,
    pred_box: list[float] | None = None,
    obs_box: list[float] | None = None,
    pred_mask: list[int] | None = None,
    obs_mask: list[int] | None = None,
    metric_name: str = "wind_speed_10m",
    episode_id: str | None = None,
    world_state_timestamp: str | None = None,
    event_ids: list[str] | None = None,
    source_providers: list[str] | None = None,
    n_bins: int = 10,
) -> Evaluation:
    eval_id = f"eval_{uuid4().hex[:12]}"
    event_ids = list(event_ids or [])
    source_providers = list(source_providers or [])
    graph = conclusion_graph(
        eval_id,
        label=f"evaluation:{metric_name}",
        episode_id=episode_id,
        world_state_timestamp=world_state_timestamp,
        world_id=world_id,
        event_ids=event_ids,
        source_providers=source_providers,
        simulation_id=simulation_id,
        kind=ProvenanceKind.DERIVED,
    )

    if observed is None or len(observed) == 0:
        return Evaluation(
            id=eval_id,
            world_id=world_id,
            simulation_id=simulation_id,
            metric_name=metric_name,
            predicted=predicted,
            observed=[],
            domain_trusted=False,
            notes="No observations for this domain — do not trust it.",
            calibration=CalibrationSummary(n=0, reliability_note="No observations; do not trust this domain."),
            episode_id=episode_id,
            world_state_timestamp=world_state_timestamp,
            event_ids=event_ids,
            source_providers=source_providers,
            provenance_graph=graph,
            bundle={
                "point": {"mae": None, "rmse": None, "mape": None},
                "probabilistic": {"brier": None, "log_loss": None, "ece": None},
                "spatial": {"geographic_distance_km": None, "iou": None, "track_divergence": None},
                "temporal": {"timing_error_minutes": None},
            },
        )
    p, o, times = predicted, observed, []
    if pred_times and obs_times:
        p, o, times = align_series(pred_times, predicted, obs_times, observed)
        if not p:
            p, o = predicted, observed
    mae_v = mae(p, o)
    rmse_v = rmse(p, o)
    mape_v = _safe_mape(p, o)
    brier_v = None
    log_loss_v = None
    ece_v = None
    bins: list[dict[str, Any]] = []
    if probabilities is not None and outcomes is not None and probabilities and outcomes:
        brier_v = brier_score(probabilities, outcomes)
        log_loss_v = log_loss(probabilities, outcomes)
        ece_v = ece(probabilities, outcomes, n_bins=n_bins)
        bins = ece_bins(probabilities, outcomes, n_bins=n_bins)
    t_err = None
    if predicted_event_minute is not None and observed_event_minute is not None:
        t_err = timing_error_minutes(predicted_event_minute, observed_event_minute)
    geo_v = None
    if pred_coords is not None and obs_coords is not None:
        geo_v = geographic_distance_km(pred_coords[0], pred_coords[1], obs_coords[0], obs_coords[1])
    iou_v = None
    if pred_box is not None and obs_box is not None:
        iou_v = iou(pred_box, obs_box)
    elif pred_mask is not None and obs_mask is not None:
        iou_v = iou(pred_mask, obs_mask)
    track_v = None
    if pred_track is not None and obs_track is not None:
        track_v = track_divergence(pred_track, obs_track)
    bundle = {
        "point": {"mae": mae_v, "rmse": rmse_v, "mape": mape_v},
        "probabilistic": {"brier": brier_v, "log_loss": log_loss_v, "ece": ece_v},
        "spatial": {"geographic_distance_km": geo_v, "iou": iou_v, "track_divergence": track_v},
        "temporal": {"timing_error_minutes": t_err},
    }
    cal = CalibrationSummary(
        n=min(len(p), len(o)),
        mae=mae_v,
        rmse=rmse_v,
        mape=mape_v,
        brier=brier_v,
        log_loss=log_loss_v,
        ece=ece_v,
        timing_error_minutes=t_err,
        geographic_distance_km=geo_v,
        iou=iou_v,
        track_divergence=track_v,
        bins=bins,
        reliability_note="Calibration is not yet established. Scenario projection, not a statement of the future.",
    )
    return Evaluation(
        id=eval_id,
        world_id=world_id,
        simulation_id=simulation_id,
        metric_name=metric_name,
        predicted=p,
        observed=o,
        times=times,
        mae=mae_v,
        rmse=rmse_v,
        mape=mape_v,
        brier=brier_v,
        log_loss=log_loss_v,
        ece=ece_v,
        timing_error_minutes=t_err,
        geographic_distance_km=geo_v,
        iou=iou_v,
        track_divergence=track_v,
        bundle=bundle,
        calibration=cal,
        notes="Predicted series is SIMULATED; observed series is OBSERVED. Kinds are never mixed.",
        domain_trusted=True,
        episode_id=episode_id,
        world_state_timestamp=world_state_timestamp,
        event_ids=event_ids,
        source_providers=source_providers,
        provenance_graph=graph,
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
    confidences: dict[str, float] = {}
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
        row = {**info, "stale": stale, "verdict": verdict}
        # freshness score in [0,1] from age vs expected — measurable, not LLM
        if "freshness" not in row:
            if age is None:
                row["freshness"] = 0.0
            else:
                row["freshness"] = max(0.0, min(1.0, 1.0 - (float(age) / float(expected))))
        if "completeness" not in row:
            row["completeness"] = 1.0 if complete else 0.0
        conf = source_confidence_from_fields(row)
        if conf is not None:
            confidences[name] = conf
            row["source_confidence"] = conf
        sources[name] = row
    return ReliabilityReport(sources=sources, untrusted_domains=untrusted, source_confidence=confidences)
