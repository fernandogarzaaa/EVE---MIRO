from eve_miro.core.evaluation.metrics import brier_score, mae, rmse, timing_error_minutes
from eve_miro.core.evaluation.reality_check import reality_check
from eve_miro.core.world.events import ProvenanceKind


def test_mae_on_known_series():
    predicted = [10.0, 12.0, 15.0]
    observed = [11.0, 12.0, 14.0]
    assert mae(predicted, observed) == 2.0 / 3.0
    assert abs(rmse(predicted, observed) - ((1**2 + 0 + 1**2) / 3) ** 0.5) < 1e-12
    ev = reality_check(
        world_id="w",
        simulation_id="s",
        predicted=predicted,
        observed=observed,
        metric_name="wind_speed_10m",
    )
    assert ev.mae == 2.0 / 3.0
    assert ev.predicted_kind is ProvenanceKind.SIMULATED
    assert ev.observed_kind is ProvenanceKind.OBSERVED


def test_timing_and_brier():
    assert timing_error_minutes(90, 60) == 30
    assert abs(brier_score([0.7, 0.2], [1, 0]) - ((0.3**2 + 0.2**2) / 2)) < 1e-9


def test_no_observations_untrusted():
    ev = reality_check(world_id="w", simulation_id="s", predicted=[1, 2], observed=[])
    assert ev.domain_trusted is False
    assert "do not trust" in ev.notes.lower()


def test_reality_check_bundle_point_prob_spatial_temporal():
    ev = reality_check(
        world_id="w",
        simulation_id="s",
        predicted=[10.0, 12.0, 15.0],
        observed=[11.0, 12.0, 14.0],
        probabilities=[0.9, 0.1],
        outcomes=[1, 0],
        predicted_event_minute=90,
        observed_event_minute=60,
        pred_coords=(0.0, 0.0),
        obs_coords=(0.0, 1.0),
        pred_box=[0.0, 0.0, 2.0, 2.0],
        obs_box=[1.0, 1.0, 3.0, 3.0],
        episode_id="episode_81",
        world_state_timestamp="2026-08-31T10:00:00+00:00",
        event_ids=["w1"],
        source_providers=["openmeteo"],
        metric_name="wind_speed_10m",
    )
    assert ev.mape is not None
    assert ev.log_loss is not None
    assert ev.ece is not None
    assert ev.timing_error_minutes == 30
    assert ev.geographic_distance_km is not None and ev.geographic_distance_km > 0
    assert ev.iou is not None
    assert set(ev.bundle) == {"point", "probabilistic", "spatial", "temporal"}
    assert ev.bundle["point"]["mae"] == ev.mae
    assert ev.bundle["probabilistic"]["brier"] == ev.brier
    assert ev.bundle["temporal"]["timing_error_minutes"] == 30
    nodes = ev.trace()
    types = {n.type for n in nodes}
    assert "conclusion" in types
    assert "source" in types or "event" in types or "simulation" in types
