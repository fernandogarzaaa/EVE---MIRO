"""Quality pipeline run before a WorldEvent is folded into WorldState."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from eve_miro.config import PHILIPPINES, Region
from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.temporal import as_utc
from eve_miro.errors import FutureLeakageError, ProvenanceError, QualityError

MAG_TOLERANCE = 0.5


class QualityIssue(BaseModel):
    code: str
    message: str
    event_id: str | None = None


class QualityReport(BaseModel):
    accepted: list[WorldEvent] = Field(default_factory=list)
    rejected: list[QualityIssue] = Field(default_factory=list)
    duplicates: list[str] = Field(default_factory=list)
    conflicted: list[str] = Field(default_factory=list)


def _in_range(event: WorldEvent) -> QualityIssue | None:
    payload = event.payload
    if event.event_type.startswith("weather"):
        temp = payload.get("temperature_2m")
        if temp is not None and not (-20 <= float(temp) <= 55):
            return QualityIssue(code="range", message=f"temperature out of range: {temp}", event_id=event.id)
        wind = payload.get("wind_speed_10m")
        if wind is not None and not (0 <= float(wind) <= 400):
            return QualityIssue(code="range", message=f"wind out of range: {wind}", event_id=event.id)
    if event.event_type.startswith("earthquake"):
        mag = payload.get("mag")
        if mag is not None and not (0 <= float(mag) <= 10):
            return QualityIssue(code="range", message=f"magnitude out of range: {mag}", event_id=event.id)
    return None


def _geo_ok(event: WorldEvent, region: Region) -> QualityIssue | None:
    if event.location is None:
        return None
    if not region.contains(event.location.lat, event.location.lon):
        return QualityIssue(
            code="geospatial",
            message=f"({event.location.lat}, {event.location.lon}) outside {region.name}",
            event_id=event.id,
        )
    return None


def _temporal_ok(event: WorldEvent, information_cutoff: datetime | None) -> None:
    t = event.temporal.effective_time
    if event.observed_at > event.ingested_at + timedelta(seconds=2):
        # clock skew tolerance; observed_at in the future of ingest is suspicious
        # but live APIs can have generation timestamps; we only hard-fail cutoff leaks
        pass
    if information_cutoff is None:
        return
    cutoff = as_utc(information_cutoff)
    event_times = [event.observed_at, event.temporal.effective_time, event.temporal.source_time]
    if event.information_cutoff is not None:
        event_times.append(event.information_cutoff)
    if any(as_utc(x) > cutoff for x in event_times):
        raise FutureLeakageError(
            f"event {event.id} at {t.isoformat()} leaks past information_cutoff {cutoff.isoformat()}"
        )


def _kind_channel(event: WorldEvent, channel: ProvenanceKind) -> None:
    if channel == ProvenanceKind.OBSERVED:
        if event.provenance.kind == ProvenanceKind.SIMULATED:
            raise ProvenanceError(
                "simulated data cannot be ingested as observed. "
                "Provenance kinds OBSERVED / DERIVED / FORECAST / SIMULATED are never mixed."
            )
        if event.provenance.kind != ProvenanceKind.OBSERVED:
            raise ProvenanceError(
                f"ingest channel OBSERVED rejected kind={event.provenance.kind.value} for event {event.id}"
            )


def _fingerprint(event: WorldEvent) -> str:
    loc = ""
    if event.location:
        loc = f"{round(event.location.lat, 3)}:{round(event.location.lon, 3)}"
    t = event.temporal.effective_time.replace(microsecond=0).isoformat()
    return f"{event.source.provider}:{event.event_type}:{loc}:{t}"


def reconcile_earthquakes(events: list[WorldEvent]) -> list[WorldEvent]:
    """If two earthquake magnitudes disagree beyond tolerance, mark both conflicted."""
    quakes = [e for e in events if e.event_type.startswith("earthquake") and e.location]
    conflicted_ids: set[str] = set()
    for i, a in enumerate(quakes):
        for b in quakes[i + 1 :]:
            dt = abs((a.temporal.effective_time - b.temporal.effective_time).total_seconds())
            dlat = abs(a.location.lat - b.location.lat)  # type: ignore[union-attr]
            dlon = abs(a.location.lon - b.location.lon)  # type: ignore[union-attr]
            if dt <= 120 and dlat <= 0.15 and dlon <= 0.15:
                ma = a.payload.get("mag")
                mb = b.payload.get("mag")
                if ma is not None and mb is not None and abs(float(ma) - float(mb)) > MAG_TOLERANCE:
                    conflicted_ids.add(a.id)
                    conflicted_ids.add(b.id)
    out: list[WorldEvent] = []
    for e in events:
        if e.id in conflicted_ids:
            prov = e.provenance.model_copy(
                update={
                    "conflicted": True,
                    "confidence": 0.4,
                    "notes": "cross-source magnitude disagreement; marked uncertain",
                }
            )
            out.append(e.model_copy(update={"provenance": prov, "payload": {**e.payload, "conflicted": True}}))
        else:
            out.append(e)
    return out


def run_quality(
    events: list[WorldEvent],
    *,
    channel: ProvenanceKind,
    region: Region | None = None,
    information_cutoff: datetime | None = None,
) -> QualityReport:
    """Schema (pydantic already), range, temporal, geospatial, duplicates, provenance."""
    region = region or PHILIPPINES
    report = QualityReport()
    seen_ids: set[str] = set()
    seen_fp: set[str] = set()
    kept: list[WorldEvent] = []
    for event in events:
        _kind_channel(event, channel)
        _temporal_ok(event, information_cutoff)
        issue = _in_range(event) or _geo_ok(event, region)
        if issue:
            report.rejected.append(issue)
            continue
        if event.id in seen_ids:
            report.duplicates.append(event.id)
            continue
        fp = _fingerprint(event)
        if fp in seen_fp:
            report.duplicates.append(event.id)
            continue
        seen_ids.add(event.id)
        seen_fp.add(fp)
        kept.append(event)
    kept = reconcile_earthquakes(kept)
    report.conflicted = [e.id for e in kept if e.provenance.conflicted]
    report.accepted = kept
    return report


def require_accepted(report: QualityReport) -> list[WorldEvent]:
    if report.rejected and not report.accepted:
        raise QualityError(f"all events rejected: {report.rejected}")
    return report.accepted
