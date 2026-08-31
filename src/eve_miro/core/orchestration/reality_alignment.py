"""RealityAligner: match predicted series to observed WorldState weather.

FORECAST-based predictions are tagged differently from OBSERVED-based.
Spatial haversine is computed when coordinates are present.
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from eve_miro.core.evaluation.forecasting import align_series
from eve_miro.core.evaluation.metrics import (
    brier_score,
    ece,
    geographic_distance_km,
    mae,
    timing_error_minutes,
)
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.state import WorldState
from eve_miro.core.world.temporal import iso


class Alignment(BaseModel):
    metric_name: str
    predicted: list[float] = Field(default_factory=list)
    observed: list[float] = Field(default_factory=list)
    times: list[str] = Field(default_factory=list)
    mae: float | None = None
    brier: float | None = None
    calibration: float | None = None
    spatial_error_km: float | None = None
    temporal_error_minutes: float | None = None
    input_provenance_kinds: list[str] = Field(default_factory=list)
    predicted_kind: ProvenanceKind = ProvenanceKind.SIMULATED
    observed_kind: ProvenanceKind = ProvenanceKind.OBSERVED


def observed_weather_series(
    events: Sequence[WorldEvent],
    *,
    field: str = "wind_speed_10m",
) -> tuple[list[str], list[float], tuple[float, float] | None]:
    times: list[str] = []
    values: list[float] = []
    coords: tuple[float, float] | None = None
    for event in events:
        if not (event.event_type or "").startswith("weather"):
            continue
        if event.kind not in {ProvenanceKind.OBSERVED, ProvenanceKind.DERIVED}:
            continue
        raw = event.payload.get(field)
        if raw is None:
            continue
        times.append(iso(event.temporal.effective_time))
        values.append(float(raw))
        if event.location is not None and coords is None:
            coords = (event.location.lat, event.location.lon)
    return times, values, coords



def observed_mobility_series(
    events: Sequence[WorldEvent],
) -> tuple[list[str], list[float], tuple[float, float] | None]:
    """Observed congestion proxy from mobility events, or explicit congestion payloads."""
    times: list[str] = []
    values: list[float] = []
    coords: tuple[float, float] | None = None
    counts: dict[str, int] = {}
    for event in events:
        et = event.event_type or ""
        raw = event.payload.get("congestion") if isinstance(event.payload, dict) else None
        if raw is not None:
            times.append(iso(event.temporal.effective_time))
            values.append(float(raw))
            if event.location is not None and coords is None:
                coords = (event.location.lat, event.location.lon)
            continue
        if not (et.startswith("aircraft") or et.startswith("vessel") or et.startswith("mobility")):
            continue
        key = iso(event.temporal.effective_time)
        counts[key] = counts.get(key, 0) + 1
        if event.location is not None and coords is None:
            coords = (event.location.lat, event.location.lon)
    if values:
        return times, values, coords
    if not counts:
        return [], [], coords
    peak = max(counts.values()) or 1
    keys = sorted(counts)
    return keys, [counts[k] / peak for k in keys], coords


class RealityAligner:
    def align(
        self,
        *,
        predicted_series: dict[str, list[float]],
        predicted_times: Sequence[str],
        t1_events: Sequence[WorldEvent],
        t1_world: WorldState | None = None,
        input_provenance_kinds: Sequence[str] | None = None,
        pred_coords: tuple[float, float] | None = None,
        metrics: Sequence[str] | None = None,
    ) -> list[Alignment]:
        kinds = [str(k).lower() for k in (input_provenance_kinds or [])]
        want = set(metrics or ["mae", "brier", "calibration", "spatial_error", "temporal_error"])
        out: list[Alignment] = []

        obs_times, obs_wind, obs_coords = observed_weather_series(t1_events, field="wind_speed_10m")
        pred_wind = list(predicted_series.get("wind_speed_10m") or [])
        pred_times = [str(t) for t in predicted_times]
        p, o, times = pred_wind, obs_wind, []
        if pred_times and obs_times and pred_wind:
            p, o, times = align_series(pred_times, pred_wind, obs_times, obs_wind)
            if not p:
                p, o, times = pred_wind, obs_wind, pred_times[: min(len(pred_wind), len(obs_wind))]
        mae_v = mae(p, o) if p and o else None

        spatial = None
        if "spatial_error" in want and pred_coords and obs_coords:
            spatial = geographic_distance_km(pred_coords[0], pred_coords[1], obs_coords[0], obs_coords[1])
        elif "spatial_error" in want and t1_world is not None and obs_coords:
            c = t1_world.geography.centroid
            spatial = geographic_distance_km(c[0], c[1], obs_coords[0], obs_coords[1])

        temporal = None
        if "temporal_error" in want and p and o:
            # peak timing in hours → minutes, using index as hour offset
            pred_peak = max(range(len(p)), key=lambda i: p[i])
            obs_peak = max(range(len(o)), key=lambda i: o[i])
            temporal = timing_error_minutes(float(pred_peak) * 60.0, float(obs_peak) * 60.0)

        brier_v = None
        cal_v = None
        if p and o and ("brier" in want or "calibration" in want):
            threshold = sorted(o)[len(o) // 2] if o else 0.0
            scale = max(max(p), 1.0)
            probs = [min(1.0, max(0.0, x / scale)) for x in p]
            outcomes = [1 if x > threshold else 0 for x in o]
            n = min(len(probs), len(outcomes))
            if n:
                if "brier" in want:
                    brier_v = brier_score(probs[:n], outcomes[:n])
                if "calibration" in want:
                    cal_v = ece(probs[:n], outcomes[:n], n_bins=5)

        out.append(
            Alignment(
                metric_name="wind_speed_10m",
                predicted=p,
                observed=o,
                times=times,
                mae=mae_v if "mae" in want else None,
                brier=brier_v,
                calibration=cal_v,
                spatial_error_km=spatial,
                temporal_error_minutes=temporal,
                input_provenance_kinds=kinds,
            )
        )

        # congestion / evacuation rate if predicted; observed mobility when t1 has it
        obs_cong_times, obs_cong, _ = observed_mobility_series(t1_events)
        for name in ("congestion", "evacuation_rate"):
            series = predicted_series.get(name)
            if not series:
                continue
            p_c, o_c, t_c = list(series), [], list(pred_times)[: len(series)]
            mae_c = None
            if name == "congestion" and obs_cong and pred_times:
                p_c, o_c, t_c = align_series(list(pred_times), list(series), obs_cong_times, obs_cong)
                if p_c and o_c:
                    mae_c = mae(p_c, o_c)
                else:
                    p_c, o_c, t_c = list(series), obs_cong, list(pred_times)[: len(series)]
            out.append(
                Alignment(
                    metric_name=name,
                    predicted=p_c,
                    observed=o_c,
                    times=t_c,
                    mae=mae_c if "mae" in want else None,
                    input_provenance_kinds=kinds,
                )
            )
        return out
