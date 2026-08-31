from datetime import datetime, timezone

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
