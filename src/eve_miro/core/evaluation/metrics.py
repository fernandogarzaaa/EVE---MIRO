"""Evaluation metrics implemented for real: MAE, RMSE, timing error, Brier score."""

from __future__ import annotations

import math


def mae(predicted: list[float], observed: list[float]) -> float:
    n = min(len(predicted), len(observed))
    if n == 0:
        raise ValueError("MAE requires a non-empty series")
    return sum(abs(predicted[i] - observed[i]) for i in range(n)) / n


def rmse(predicted: list[float], observed: list[float]) -> float:
    n = min(len(predicted), len(observed))
    if n == 0:
        raise ValueError("RMSE requires a non-empty series")
    return math.sqrt(sum((predicted[i] - observed[i]) ** 2 for i in range(n)) / n)


def timing_error_minutes(predicted_event_t: float, observed_event_t: float) -> float:
    """Absolute timing error in minutes between two epoch-seconds or minute offsets."""
    return abs(predicted_event_t - observed_event_t)


def brier_score(probabilities: list[float], outcomes: list[int]) -> float:
    """Mean squared error of probabilistic forecasts. outcomes are 0/1."""
    n = min(len(probabilities), len(outcomes))
    if n == 0:
        raise ValueError("Brier score requires a non-empty series")
    return sum((probabilities[i] - outcomes[i]) ** 2 for i in range(n)) / n
