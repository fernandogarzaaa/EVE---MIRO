"""Experience graph: CANDIDATE → VALIDATED → REPLICATED / CONFLICTING / …

EVE artifacts stay memory/context for the next seed/run. They are never
claimed as weight updates.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from eve_miro.core.world.temporal import utcnow


class ExperienceStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    REPLICATED = "REPLICATED"
    GENERALIZED = "GENERALIZED"
    RETAINED = "RETAINED"
    REJECTED = "REJECTED"
    CONFLICTING = "CONFLICTING"


class ExperienceNode(BaseModel):
    id: str
    state: ExperienceStatus = ExperienceStatus.CANDIDATE
    layer: str = "agent"
    fingerprint: str = ""
    metric_mae: float | None = None
    artifact: dict[str, Any] | None = None
    similar_to: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())


def fingerprint_of(layer: str, artifact: dict[str, Any] | None, extra: str = "") -> str:
    blob = " ".join(
        [
            layer,
            str((artifact or {}).get("experience") or ""),
            " ".join(str(c) for c in ((artifact or {}).get("conditions") or [])),
            extra,
        ]
    ).strip().lower()
    return blob or f"{layer}:generic"


class ExperienceGraph:
    """In-memory graph of experience artifacts and their validation states."""

    def __init__(self) -> None:
        self._nodes: dict[str, ExperienceNode] = {}

    def add_candidate(
        self,
        experience_id: str,
        *,
        layer: str = "agent",
        fingerprint: str = "",
        artifact: dict[str, Any] | None = None,
        metric_mae: float | None = None,
        notes: str = "",
    ) -> ExperienceNode:
        node = ExperienceNode(
            id=experience_id,
            state=ExperienceStatus.CANDIDATE,
            layer=layer,
            fingerprint=fingerprint or fingerprint_of(layer, artifact),
            artifact=artifact,
            metric_mae=metric_mae,
            notes=notes,
        )
        self._nodes[experience_id] = node
        return node

    def get(self, experience_id: str) -> ExperienceNode | None:
        return self._nodes.get(experience_id)

    def nodes(self) -> list[ExperienceNode]:
        return list(self._nodes.values())

    def find_by_fingerprint(self, fingerprint: str) -> list[ExperienceNode]:
        return [n for n in self._nodes.values() if n.fingerprint == fingerprint]

    def mark_validated(self, experience_id: str) -> ExperienceNode:
        node = self._require(experience_id)
        peers = [
            n
            for n in self.find_by_fingerprint(node.fingerprint)
            if n.id != node.id and n.state in {ExperienceStatus.VALIDATED, ExperienceStatus.REPLICATED}
        ]
        if peers:
            node.state = ExperienceStatus.REPLICATED
            node.similar_to = [p.id for p in peers]
            node.notes = (node.notes + " ").strip() + "second similar run → REPLICATED"
        else:
            node.state = ExperienceStatus.VALIDATED
        self._nodes[experience_id] = node
        return node

    def mark_replicated(self, experience_id: str, similar_to: str | None = None) -> ExperienceNode:
        node = self._require(experience_id)
        node.state = ExperienceStatus.REPLICATED
        if similar_to and similar_to not in node.similar_to:
            node.similar_to.append(similar_to)
        self._nodes[experience_id] = node
        return node

    def mark_conflicting(self, experience_id: str, reason: str = "") -> ExperienceNode:
        node = self._require(experience_id)
        node.state = ExperienceStatus.CONFLICTING
        if reason:
            node.notes = (node.notes + " " + reason).strip()
        self._nodes[experience_id] = node
        return node

    def mark_rejected(self, experience_id: str, reason: str = "") -> ExperienceNode:
        node = self._require(experience_id)
        node.state = ExperienceStatus.REJECTED
        if reason:
            node.notes = (node.notes + " " + reason).strip()
        self._nodes[experience_id] = node
        return node

    def maybe_conflict_on_mae(
        self,
        experience_id: str,
        mae: float,
        *,
        relative_threshold: float = 0.5,
    ) -> ExperienceNode:
        """If a peer with the same fingerprint has a contradicting MAE, mark CONFLICTING."""
        node = self._require(experience_id)
        node.metric_mae = mae
        for peer in self.find_by_fingerprint(node.fingerprint):
            if peer.id == node.id or peer.metric_mae is None:
                continue
            denom = max(abs(peer.metric_mae), 1e-6)
            if abs(mae - peer.metric_mae) / denom > relative_threshold:
                return self.mark_conflicting(
                    experience_id,
                    reason=f"contradicting metric mae={mae} vs {peer.metric_mae} ({peer.id})",
                )
        self._nodes[experience_id] = node
        return node

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {s.value: 0 for s in ExperienceStatus}
        for n in self._nodes.values():
            counts[n.state.value] = counts.get(n.state.value, 0) + 1
        return {
            "n": len(self._nodes),
            "states": counts,
            "note": "EVE artifacts are memory/context for the next seed/run, never weight updates.",
        }

    def _require(self, experience_id: str) -> ExperienceNode:
        node = self._nodes.get(experience_id)
        if node is None:
            raise KeyError(f"experience {experience_id} not in graph")
        return node
