from eve_miro.core.world.events import ProvenanceKind
from eve_miro.core.world.quality import run_quality
from tests.helpers import make_event


def test_earthquake_magnitude_conflict_marked_uncertain():
    a = make_event(
        "usgs:a",
        "2024-11-04T00:00:00Z",
        event_type="earthquake.event",
        payload={"mag": 4.0, "place": "x"},
        lat=14.6,
        lon=121.0,
        provider="usgs",
    )
    b = make_event(
        "phivolcs:b",
        "2024-11-04T00:00:30Z",
        event_type="earthquake.event",
        payload={"mag": 5.2, "place": "x"},
        lat=14.61,
        lon=121.01,
        provider="phivolcs",
    )
    report = run_quality([a, b], channel=ProvenanceKind.OBSERVED)
    assert len(report.accepted) == 2
    assert report.conflicted
    assert all(e.provenance.conflicted for e in report.accepted)



def test_earthquake_magnitude_agreement_high_confidence_consensus():
    a = make_event(
        "usgs:c",
        "2024-11-04T00:00:00Z",
        event_type="earthquake.event",
        payload={"mag": 4.0, "place": "x"},
        lat=14.6,
        lon=121.0,
        provider="usgs",
    )
    b = make_event(
        "phivolcs:d",
        "2024-11-04T00:00:30Z",
        event_type="earthquake.event",
        payload={"mag": 4.2, "place": "x"},
        lat=14.61,
        lon=121.01,
        provider="phivolcs",
    )
    report = run_quality([a, b], channel=ProvenanceKind.OBSERVED)
    assert len(report.accepted) == 2
    assert not report.conflicted
    assert set(report.consensus) == {"usgs:c", "phivolcs:d"}
    for e in report.accepted:
        assert e.provenance.conflicted is False
        assert e.provenance.confidence == 0.95
        assert e.payload.get("consensus") is True
        assert "consensus" in (e.provenance.notes or "")
