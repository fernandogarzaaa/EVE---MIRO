"""Optional Postgres/PostGIS event store. Tests do not require it."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eve_miro.core.world.events import ProvenanceKind, WorldEvent
from eve_miro.core.world.quality import run_quality
from eve_miro.core.world.temporal import as_utc


class PostgresEventStore:
    def __init__(self, url: str) -> None:
        from sqlalchemy import create_engine, text

        self._engine = create_engine(url, future=True)
        self._text = text

    def append(
        self,
        world_id: str,
        event: WorldEvent,
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
    ) -> None:
        self.append_many(world_id, [event], channel=channel)

    def append_many(
        self,
        world_id: str,
        events: list[WorldEvent],
        *,
        channel: ProvenanceKind = ProvenanceKind.OBSERVED,
        information_cutoff: datetime | None = None,
    ) -> list[WorldEvent]:
        report = run_quality(events, channel=channel, information_cutoff=information_cutoff)
        sql = self._text(
            """
            INSERT INTO events (
              id, world_id, source, observed_at, ingested_at, lat, lon,
              entity, event_type, payload, provenance, temporal, information_cutoff, provenance_kind
            ) VALUES (
              :id, :world_id, CAST(:source AS jsonb), :observed_at, :ingested_at, :lat, :lon,
              CAST(:entity AS jsonb), :event_type, CAST(:payload AS jsonb),
              CAST(:provenance AS jsonb), CAST(:temporal AS jsonb), :information_cutoff, :provenance_kind
            ) ON CONFLICT (id) DO NOTHING
            """
        )
        accepted: list[WorldEvent] = []
        with self._engine.begin() as conn:
            for event in report.accepted:
                conn.execute(
                    sql,
                    {
                        "id": event.id,
                        "world_id": world_id,
                        "source": event.source.model_dump_json(),
                        "observed_at": event.observed_at,
                        "ingested_at": event.ingested_at,
                        "lat": event.location.lat if event.location else None,
                        "lon": event.location.lon if event.location else None,
                        "entity": event.entity.model_dump_json() if event.entity else None,
                        "event_type": event.event_type,
                        "payload": __import__("json").dumps(event.payload),
                        "provenance": event.provenance.model_dump_json(),
                        "temporal": event.temporal.model_dump_json(),
                        "information_cutoff": event.information_cutoff,
                        "provenance_kind": event.provenance.kind.value,
                    },
                )
                accepted.append(event)
        return accepted

    def list(
        self,
        world_id: str,
        *,
        up_to: datetime | None = None,
        kinds: list[ProvenanceKind] | None = None,
    ) -> list[WorldEvent]:
        clauses = ["world_id = :world_id"]
        params: dict[str, Any] = {"world_id": world_id}
        if up_to is not None:
            clauses.append("observed_at <= :up_to")
            params["up_to"] = as_utc(up_to)
        sql = f"SELECT payload_event FROM events_view WHERE {' AND '.join(clauses)} ORDER BY seq"
        # fall back to reconstructing from columns if view is absent
        with self._engine.begin() as conn:
            try:
                rows = conn.execute(self._text(sql), params).fetchall()
                return [WorldEvent.model_validate_json(r[0]) for r in rows]
            except Exception:
                q = "SELECT id, source, observed_at, ingested_at, lat, lon, entity, event_type, payload, provenance, temporal, information_cutoff FROM events WHERE world_id = :world_id ORDER BY seq"
                rows = conn.execute(self._text(q), params).fetchall()
        out: list[WorldEvent] = []
        import json

        for r in rows:
            loc = None
            if r.lat is not None:
                loc = {"lat": r.lat, "lon": r.lon}
            out.append(
                WorldEvent.model_validate(
                    {
                        "id": r.id,
                        "source": json.loads(r.source) if isinstance(r.source, str) else r.source,
                        "observed_at": r.observed_at,
                        "ingested_at": r.ingested_at,
                        "location": loc,
                        "entity": json.loads(r.entity) if r.entity else None,
                        "event_type": r.event_type,
                        "payload": json.loads(r.payload) if isinstance(r.payload, str) else r.payload,
                        "provenance": json.loads(r.provenance) if isinstance(r.provenance, str) else r.provenance,
                        "temporal": json.loads(r.temporal) if isinstance(r.temporal, str) else r.temporal,
                        "information_cutoff": r.information_cutoff,
                    }
                )
            )
        if kinds:
            allowed = set(kinds)
            out = [e for e in out if e.provenance.kind in allowed]
        return out
