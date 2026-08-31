from eve_miro.core.world.events import ProvenanceKind
from eve_miro.errors import ProvenanceError
from eve_miro.storage.event_store import InMemoryEventStore
from tests.helpers import make_event
import pytest


def test_simulated_cannot_be_ingested_as_observed():
    store = InMemoryEventStore()
    event = make_event("sim-1", "2026-08-31T10:00:00Z", kind=ProvenanceKind.SIMULATED)
    with pytest.raises(ProvenanceError, match="simulated data cannot be ingested as observed"):
        store.append_many("w1", [event], channel=ProvenanceKind.OBSERVED)


def test_forecast_rejected_on_observed_channel():
    store = InMemoryEventStore()
    event = make_event("fc-1", "2026-08-31T10:00:00Z", kind=ProvenanceKind.FORECAST)
    with pytest.raises(ProvenanceError):
        store.append_many("w1", [event], channel=ProvenanceKind.OBSERVED)


def test_observed_ingests_on_observed_channel():
    store = InMemoryEventStore()
    event = make_event("obs-1", "2026-08-31T10:00:00Z", kind=ProvenanceKind.OBSERVED)
    stored = store.append_many("w1", [event], channel=ProvenanceKind.OBSERVED)
    assert len(stored) == 1
    assert stored[0].kind is ProvenanceKind.OBSERVED
