from datetime import datetime, timezone

import pytest

from eve_miro.core.world.projector import project_world_state
from eve_miro.storage.event_store import InMemoryEventStore
from eve_miro.core.world.events import ProvenanceKind
from tests.helpers import make_event


def test_worldstate_reconstructed_from_event_log():
    store = InMemoryEventStore()
    events = [
        make_event("w1", "2026-08-31T08:00:00Z", payload={"wind_speed_10m": 12.0, "temperature_2m": 28.0}),
        make_event("w2", "2026-08-31T09:00:00Z", payload={"wind_speed_10m": 18.0, "temperature_2m": 29.0}),
        make_event(
            "q1",
            "2026-08-31T08:30:00Z",
            event_type="earthquake.event",
            payload={"mag": 4.2, "place": "test"},
        ),
    ]
    store.append_many("world", events, channel=ProvenanceKind.OBSERVED)
    log = store.list("world")
    t = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
    state = project_world_state("world", log, at=t, information_cutoff=t)
    assert set(state.events) == {"w1", "w2", "q1"}
    assert state.environment.weather["latest"]["wind_speed_10m"] == 18.0
    assert state.environment.seismic["count"] == 1
    assert state.information_cutoff == t
    # provenance graph traces state back to sources
    why = state.provenance_graph.why(f"state:world:{t.isoformat()}")
    types = {n.type for n in why}
    assert "source" in types and "event" in types and "state" in types
    sources = state.provenance_graph.sources_for(f"state:world:{t.isoformat()}")
    assert sources


def test_market_price_folded_into_economy():
    events = [
        make_event(
            "px1",
            "2026-08-31T08:00:00Z",
            event_type="market.price",
            payload={"symbol": "bitcoin", "price": 64000.0, "currency": "usd"},
        ),
        make_event(
            "px2",
            "2026-08-31T09:00:00Z",
            event_type="market.price",
            payload={"id": "bitcoin", "usd": 64100.0},
        ),
    ]
    t = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
    state = project_world_state("world", events, at=t, information_cutoff=t)
    market = state.economy.indicators["market"]
    assert market["n"] == 2
    assert market["latest"]["price"] == 64100.0
    assert market["latest"]["kind"] == "observed"
    why = state.provenance_graph.trace(f"state:world:{t.isoformat()}")
    assert any(n.type == "source" for n in why)


def test_haiyan_cutoff_rejects_next_day_event():
    from eve_miro.core.simulation.replay import replay_world
    from eve_miro.errors import FutureLeakageError, ReplayError

    cutoff = datetime(2013, 11, 7, 12, 0, tzinfo=timezone.utc)
    events = [
        make_event("haiyan-ok", "2013-11-07T06:00:00Z"),
        make_event("haiyan-late", "2013-11-08T00:00:00Z"),
    ]
    with pytest.raises((FutureLeakageError, ReplayError)):
        replay_world("haiyan", events, at=cutoff, information_cutoff=cutoff)
