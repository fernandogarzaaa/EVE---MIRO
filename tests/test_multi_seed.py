"""Mean/variance over seeds; a single run is not treated as truth."""

from __future__ import annotations

import pytest

from eve_miro.core.orchestration.closed_loop import ClosedLoop, split_at_cutoff, summarize_scalar
from eve_miro.core.orchestration.experiment import load_experiment
from eve_miro.providers.common import load_fixture
from eve_miro.providers.weather import OpenMeteoProvider
from eve_miro.storage.event_store import InMemoryEventStore


def test_summarize_scalar_mean_variance_interval():
    stats = summarize_scalar([0.1, 0.2, 0.3])
    assert stats["n"] == 3
    assert abs(stats["mean"] - 0.2) < 1e-9
    assert stats["variance"] > 0
    lo, hi = stats["interval"]
    assert lo < stats["mean"] < hi


@pytest.mark.asyncio
async def test_closed_loop_aggregates_distribution_not_single_seed():
    spec = load_experiment()
    events = OpenMeteoProvider(mode="archive").normalize(load_fixture("openmeteo_manila_archive.json"))
    t0, t1 = split_at_cutoff(events, spec.cutoff)
    result = await ClosedLoop().run(
        spec,
        InMemoryEventStore(),
        t0,
        t1,
        agents=24,
        seeds=[1, 2, 3],
        horizon_hours=4,
        world_id="w_seeds",
    )
    for sc_id, agg in result.aggregates.items():
        assert agg.n_seeds == 3
        assert "mean" in agg.evacuation_rate
        assert "variance" in agg.evacuation_rate
        assert "interval" in agg.evacuation_rate
        # evacuation rate varies with seed (stub RNG); wind series is hour-deterministic
        assert agg.evacuation_rate["n"] == 3
        assert agg.mean_predicted_series.get("wind_speed_10m")
        # evaluation is attached to the aggregate (seed is None on ledger)
    recs = [r for r in result.ledger_record_ids]
    assert recs
    assert len(result.seed_runs) == 9  # 3 scenarios × 3 seeds
    assert result.evaluations
    for e in result.evaluations:
        assert e.get("n_seeds") == 3
