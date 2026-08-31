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
