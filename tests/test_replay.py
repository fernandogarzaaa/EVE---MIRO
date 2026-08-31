from datetime import datetime, timezone

import pytest

from eve_miro.core.simulation.replay import assert_no_future_events
from eve_miro.core.simulation.scenarios import load_scenario
from eve_miro.errors import ReplayError
from tests.helpers import make_event


def test_scenario_yaml_loads():
    sc = load_scenario()
    assert sc.name == "typhoon_manila_001"
    assert sc.population == 1000
    assert sc.simulated_hours == 72
    assert sc.random_seed == 48291


def test_replay_refuses_post_cutoff_events():
    cutoff = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    events = [make_event("late", "2026-08-31T11:00:00Z")]
    with pytest.raises(ReplayError):
        assert_no_future_events(events, cutoff)
