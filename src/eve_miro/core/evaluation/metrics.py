"""Evaluation metrics implemented for real (pure Python).

Point: MAE, RMSE, MAPE.
Probabilistic: Brier, log loss, ECE.
Spatial: IoU, haversine, track divergence.
Distributional: KL, JS, 1-Wasserstein.
Temporal: timing error (minutes).
"""

from __future__ import annotations

import math
from typing import Sequence

EPS = 1e-12
LOG_LOSS_CLIP = 1e-15
EARTH_RADIUS_KM = 6371.0


def _pair_len(a: Sequence[float], b: Sequence[float], name: str) -> int:
    n = min(len(a), len(b))
    if n == 0:
        raise ValueError(f"{name} requires a non-empty series")
    return n


def mae(predicted: list[float], observed: list[float]) -> float:
    n = _pair_len(predicted, observed, "MAE")
    return sum(abs(predicted[i] - observed[i]) for i in range(n)) / n


def rmse(predicted: list[float], observed: list[float]) -> float:
    n = _pair_len(predicted, observed, "RMSE")
    return math.sqrt(sum((predicted[i] - observed[i]) ** 2 for i in range(n)) / n)


def mape(predicted: list[float], observed: list[float]) -> float:
    """Mean absolute percentage error as a fraction (not percent). Zeros in observed are skipped."""
    n = _pair_len(predicted, observed, "MAPE")
    total = 0.0
    count = 0
    for i in range(n):
        if observed[i] == 0:
            continue
        total += abs(predicted[i] - observed[i]) / abs(observed[i])
        count += 1
    if count == 0:
        raise ValueError("MAPE requires at least one non-zero observed value")
    return total / count


def timing_error_minutes(predicted_event_t: float, observed_event_t: float) -> float:
    """Absolute timing error in minutes between two epoch-seconds or minute offsets."""
    return abs(predicted_event_t - observed_event_t)


def brier_score(probabilities: list[float], outcomes: list[int]) -> float:
    """Mean squared error of probabilistic forecasts. outcomes are 0/1."""
    n = _pair_len(probabilities, outcomes, "Brier score")
    return sum((probabilities[i] - outcomes[i]) ** 2 for i in range(n)) / n


def log_loss(probabilities: list[float], outcomes: list[int], *, eps: float = LOG_LOSS_CLIP) -> float:
    """Binary log loss with probabilities clipped to (eps, 1-eps)."""
    n = _pair_len(probabilities, outcomes, "log_loss")
    lo, hi = eps, 1.0 - eps
    total = 0.0
    for i in range(n):
        p = min(hi, max(lo, float(probabilities[i])))
        y = float(outcomes[i])
        total += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return total / n


def ece(probabilities: list[float], outcomes: list[int], n_bins: int = 10) -> float:
    """Expected calibration error: sum_m (|B_m|/n) * |acc(B_m) - conf(B_m)|."""
    if n_bins < 1:
        raise ValueError("ece requires n_bins >= 1")
    n = _pair_len(probabilities, outcomes, "ECE")
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for i in range(n):
        p = min(1.0, max(0.0, float(probabilities[i])))
        b = min(n_bins - 1, int(p * n_bins))
        buckets[b].append((p, float(outcomes[i])))
    score = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        score += (len(bucket) / n) * abs(acc - conf)
    return score


def ece_bins(probabilities: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict[str, float | int]]:
    """Per-bin calibration table used by CalibrationSummary."""
    n = _pair_len(probabilities, outcomes, "ECE")
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for i in range(n):
        p = min(1.0, max(0.0, float(probabilities[i])))
        b = min(n_bins - 1, int(p * n_bins))
        buckets[b].append((p, float(outcomes[i])))
    rows: list[dict[str, float | int]] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        rows.append(
            {
                "bin": i,
                "n": len(bucket),
                "confidence": conf,
                "accuracy": acc,
                "gap": abs(acc - conf),
            }
        )
    return rows


def _looks_like_box(values: Sequence[float]) -> bool:
    return len(values) == 4 and any(float(v) not in (0.0, 1.0) for v in values)


def _iou_boxes(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = (float(a[0]), float(a[1]), float(a[2]), float(a[3]))
    bx1, by1, bx2, by2 = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
    if ax2 < ax1:
        ax1, ax2 = ax2, ax1
    if ay2 < ay1:
        ay1, ay2 = ay2, ay1
    if bx2 < bx1:
        bx1, bx2 = bx2, bx1
    if by2 < by1:
        by1, by2 = by2, by1
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 1.0 if area_a == 0 and area_b == 0 else 0.0
    return inter / union


def _iou_masks(a: Sequence[float], b: Sequence[float]) -> float:
    n = _pair_len(a, b, "IoU")
    inter = 0.0
    union = 0.0
    for i in range(n):
        ai = 1.0 if a[i] else 0.0
        bi = 1.0 if b[i] else 0.0
        inter += ai * bi
        union += 1.0 if (ai or bi) else 0.0
    if union == 0:
        return 1.0
    return inter / union


def iou(a: list[float] | list[int], b: list[float] | list[int]) -> float:
    """Intersection-over-union of two boxes [x1,y1,x2,y2] or two 1D 0/1 masks."""
    if _looks_like_box(a) and _looks_like_box(b):
        return _iou_boxes(a, b)
    return _iou_masks(a, b)


def geographic_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def track_divergence(
    track_a: list[tuple[float, float]],
    track_b: list[tuple[float, float]],
) -> float:
    """Mean haversine distance (km) along two lat/lon tracks."""
    n = min(len(track_a), len(track_b))
    if n == 0:
        raise ValueError("track_divergence requires non-empty tracks")
    total = 0.0
    for i in range(n):
        lat1, lon1 = track_a[i]
        lat2, lon2 = track_b[i]
        total += geographic_distance_km(lat1, lon1, lat2, lon2)
    return total / n


def _smooth_probs(probs: Sequence[float], eps: float) -> list[float]:
    s = [max(0.0, float(p)) + eps for p in probs]
    z = sum(s)
    if z <= 0:
        n = len(s)
        if n == 0:
            raise ValueError("probability vector is empty")
        return [1.0 / n] * n
    return [x / z for x in s]


def kl_divergence(p: list[float], q: list[float], *, epsilon: float = EPS) -> float:
    """Discrete KL(p || q) with epsilon smoothing, natural log."""
    n = _pair_len(p, q, "KL")
    ps = _smooth_probs(p[:n], epsilon)
    qs = _smooth_probs(q[:n], epsilon)
    return sum(ps[i] * math.log(ps[i] / qs[i]) for i in range(n))


def js_divergence(p: list[float], q: list[float], *, epsilon: float = EPS) -> float:
    """Jensen–Shannon divergence (natural log). JS(p,p)=0."""
    n = _pair_len(p, q, "JS")
    ps = _smooth_probs(p[:n], epsilon)
    qs = _smooth_probs(q[:n], epsilon)
    m = [0.5 * (ps[i] + qs[i]) for i in range(n)]
    return 0.5 * kl_divergence(ps, m, epsilon=0.0) + 0.5 * kl_divergence(qs, m, epsilon=0.0)


def wasserstein_1d(u: list[float], v: list[float]) -> float:
    """1-Wasserstein distance via sorted samples / quantile functions.

    Equal-length samples: mean |sort(u)_i - sort(v)_i|.
    Unequal length: mean absolute difference of quantile functions on a shared grid.
    """
    if not u or not v:
        raise ValueError("wasserstein_1d requires non-empty samples")
    us = sorted(float(x) for x in u)
    vs = sorted(float(x) for x in v)
    if len(us) == len(vs):
        return sum(abs(a - b) for a, b in zip(us, vs)) / len(us)

    def quantile(sorted_s: list[float], t: float) -> float:
        if len(sorted_s) == 1:
            return sorted_s[0]
        idx = t * (len(sorted_s) - 1)
        lo = int(math.floor(idx))
        hi = min(lo + 1, len(sorted_s) - 1)
        w = idx - lo
        return sorted_s[lo] * (1.0 - w) + sorted_s[hi] * w

    n = max(len(us), len(vs))
    ts = [i / (n - 1) for i in range(n)] if n > 1 else [0.0]
    return sum(abs(quantile(us, t) - quantile(vs, t)) for t in ts) / n
