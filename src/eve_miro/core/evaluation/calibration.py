"""Calibration summary persisted with each Evaluation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CalibrationSummary(BaseModel):
    n: int = 0
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
    reliability_note: str = "Calibration is not yet established for v1 scenario projections."
    bins: list[dict[str, Any]] = Field(default_factory=list)
