from datetime import datetime, timezone

import pytest

from eve_miro.core.simulation.replay import replay_world
from eve_miro.core.world.projector import project_world_state
from eve_miro.errors import FutureLeakageError, ReplayError
from tests.helpers import make_event

CUTOFF = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)


def test_information_cutoff_leakage_rejected_by_replay():
    events = [
        make_event("e0", "2026-08-31T09:00:00Z"),
        make_event("e1", "2026-08-31T12:00:00Z"),  # after cutoff
    ]
    with pytest.raises((FutureLeakageError, ReplayError)):
        replay_world("w", events, at=CUTOFF, information_cutoff=CUTOFF)


def test_reconstruction_does_not_include_future_of_at():
    events = [
        make_event("e0", "2026-08-31T09:00:00Z", payload={"wind_speed_10m": 5}),
        make_event("e1", "2026-08-31T11:00:00Z", payload={"wind_speed_10m": 50}),
    ]
    # later events exist in the log but WorldState(t=09:00) must not see 11:00
    state = project_world_state(
        "w",
        events,
        at=datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc),
        information_cutoff=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        reject_leaks=False,
    )
    assert "e0" in state.events
    assert "e1" not in state.events
