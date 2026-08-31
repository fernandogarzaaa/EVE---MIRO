"""Known-value tests for evaluation metrics."""

from __future__ import annotations

import math

from eve_miro.core.evaluation.metrics import (
    EARTH_RADIUS_KM,
    brier_score,
    ece,
    geographic_distance_km,
    iou,
    js_divergence,
    kl_divergence,
    log_loss,
    mae,
    mape,
    rmse,
    timing_error_minutes,
    track_divergence,
    wasserstein_1d,
)


def test_mae_rmse_mape_known():
    predicted = [10.0, 12.0, 15.0]
    observed = [11.0, 12.0, 14.0]
    assert mae(predicted, observed) == 2.0 / 3.0
    assert abs(rmse(predicted, observed) - ((1**2 + 0 + 1**2) / 3) ** 0.5) < 1e-12
    assert abs(mape([11.0, 12.0], [10.0, 10.0]) - 0.15) < 1e-12


def test_log_loss_clipped_known():
    # y=1,p=0.8 and y=0,p=0.2 → both contribute -log(0.8)
    got = log_loss([0.8, 0.2], [1, 0])
    assert abs(got - (-math.log(0.8))) < 1e-12
    # clip: p=0 would be -log(eps)
    clipped = log_loss([0.0], [1], eps=1e-15)
    assert abs(clipped - (-math.log(1e-15))) < 1e-9


def test_ece_known_bins():
    # two well-separated bins: 0.1 vs 0, 0.9 vs 1 → ECE = 0.1
    got = ece([0.9, 0.9, 0.1, 0.1], [1, 1, 0, 0], n_bins=10)
    assert abs(got - 0.1) < 1e-12
    # perfectly wrong certainty
    assert abs(ece([1.0, 1.0], [0, 0], n_bins=10) - 1.0) < 1e-12


def test_iou_boxes_and_masks():
    assert abs(iou([0, 0, 2, 2], [1, 1, 3, 3]) - 1.0 / 7.0) < 1e-12
    assert iou([0, 0, 2, 2], [0, 0, 2, 2]) == 1.0
    assert iou([0, 0, 2, 2], [5, 5, 7, 7]) == 0.0
    assert abs(iou([1, 1, 0, 0], [1, 0, 1, 0]) - 1.0 / 3.0) < 1e-12
    assert iou([0, 0, 0, 0], [0, 0, 0, 0]) == 1.0


def test_haversine_and_track_divergence():
    equator_1deg = EARTH_RADIUS_KM * math.pi / 180.0
    d = geographic_distance_km(0.0, 0.0, 0.0, 1.0)
    assert abs(d - equator_1deg) < 1e-9
    assert geographic_distance_km(14.5995, 120.9842, 14.5995, 120.9842) == 0.0
    track_a = [(0.0, 0.0), (0.0, 1.0)]
    track_b = [(0.0, 0.0), (0.0, 1.0)]
    assert track_divergence(track_a, track_b) == 0.0
    div = track_divergence([(0.0, 0.0), (0.0, 1.0)], [(0.0, 0.0), (0.0, 0.0)])
    assert abs(div - equator_1deg / 2.0) < 1e-9


def test_kl_js_identical_zero():
    p = [0.25, 0.25, 0.5]
    assert abs(kl_divergence(p, p)) < 1e-12
    assert abs(js_divergence(p, p)) < 1e-12
    q = [0.5, 0.5]
    r = [0.9, 0.1]
    assert js_divergence(q, r) == js_divergence(r, q)
    assert kl_divergence(q, r) > 0


def test_wasserstein_1d_sorted_mean_abs():
    assert wasserstein_1d([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]) == 1.0
    assert wasserstein_1d([0.0, 1.0, 3.0], [5.0, 6.0, 8.0]) == 5.0
    assert wasserstein_1d([1.0, 2.0], [1.0, 2.0]) == 0.0


def test_timing_and_brier_still_hold():
    assert timing_error_minutes(90, 60) == 30
    assert abs(brier_score([0.7, 0.2], [1, 0]) - ((0.3**2 + 0.2**2) / 2)) < 1e-9
