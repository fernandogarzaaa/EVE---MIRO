"""Reality ledger: FORECAST inputs tagged; CORRECT/INCORRECT from known numbers."""

from __future__ import annotations

from eve_miro.core.reality.ledger import RealityLedger


def test_forecast_inputs_tagged_and_correct_incorrect_from_known_numbers():
    ledger = RealityLedger()
    observed_rec = ledger.record_prediction(
        experiment_id="exp_l",
        scenario_id="baseline",
        model="mirofish",
        seed=1,
        cutoff="2024-11-01T00:00:00Z",
        source_versions={"openmeteo": "archive"},
        input_provenance_kinds=["observed"],
        domain="weather",
        predicted=[10.0, 12.0, 14.0],
        observed=[10.0, 12.0, 14.0],
    )
    assert "observed" in observed_rec.input_provenance_kinds
    assert "forecast" not in observed_rec.input_provenance_kinds
    assert observed_rec.verdict == "CORRECT"
    assert observed_rec.mae is not None
    assert observed_rec.mae == 0.0

    forecast_rec = ledger.record_prediction(
        experiment_id="exp_l",
        scenario_id="baseline",
        model="mirofish",
        seed=2,
        cutoff="2024-11-01T00:00:00Z",
        source_versions={"openmeteo": "forecast"},
        input_provenance_kinds=["forecast"],
        domain="weather",
        predicted=[10.0, 12.0],
        observed=[50.0, 60.0],
    )
    assert "forecast" in forecast_rec.input_provenance_kinds
    assert forecast_rec.verdict == "INCORRECT"
    assert forecast_rec.mae is not None
    assert forecast_rec.mae > 1.0

    rows = ledger.list()
    assert len(rows) == 2
    tagged = [r for r in rows if "forecast" in r.input_provenance_kinds]
    assert tagged and tagged[0].id == forecast_rec.id
