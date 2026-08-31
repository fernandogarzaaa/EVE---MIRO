"""Source confidence from measurable fields only. Never an LLM."""

from __future__ import annotations

from typing import Any

# Weights sum to 1.0. Documented in docs/evaluation.md.
SOURCE_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "reliability": 0.25,
    "freshness": 0.20,
    "completeness": 0.20,
    "cross_source_agreement": 0.20,
    "historical_accuracy": 0.15,
}

MEASURABLE_FIELDS = tuple(SOURCE_CONFIDENCE_WEIGHTS.keys())


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def source_confidence(
    *,
    reliability: float,
    freshness: float,
    completeness: float,
    cross_source_agreement: float,
    historical_accuracy: float,
) -> float:
    """Weighted mean of measurable source-quality fields, clipped to [0, 1].

    source_confidence =
        0.25 * reliability
      + 0.20 * freshness
      + 0.20 * completeness
      + 0.20 * cross_source_agreement
      + 0.15 * historical_accuracy

    Inputs must already be in [0, 1] (callers map age/completeness/agreement
    onto that scale). This function never calls an LLM and never invents
    a score from text.
    """
    fields = {
        "reliability": reliability,
        "freshness": freshness,
        "completeness": completeness,
        "cross_source_agreement": cross_source_agreement,
        "historical_accuracy": historical_accuracy,
    }
    for name, raw in fields.items():
        v = float(raw)
        if v < 0.0 or v > 1.0:
            raise ValueError(f"{name} must be in [0, 1], got {raw}")
        fields[name] = v
    score = sum(SOURCE_CONFIDENCE_WEIGHTS[k] * fields[k] for k in MEASURABLE_FIELDS)
    return _clip01(score)


def source_confidence_from_fields(info: dict[str, Any]) -> float | None:
    """Return source_confidence if all five measurable fields are present; else None."""
    missing = [k for k in MEASURABLE_FIELDS if k not in info or info[k] is None]
    if missing:
        return None
    return source_confidence(**{k: float(info[k]) for k in MEASURABLE_FIELDS})
