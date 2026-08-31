"""Provenance graph: conclusions → experiences → states → events → sources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eve_miro.core.world.events import ProvenanceKind
from eve_miro.errors import ProvenanceError

NodeType = Literal["source", "event", "state", "experience", "conclusion", "simulation"]


class ProvenanceNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    type: NodeType
    label: str
    provenance_kind: ProvenanceKind | None = None


class ProvenanceEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    src: str
    dst: str
    rel: str = "derived_from"


class ProvenanceGraph(BaseModel):
    """Directed graph used to answer 'why did the simulator predict this?'."""

    nodes: list[ProvenanceNode] = Field(default_factory=list)
    edges: list[ProvenanceEdge] = Field(default_factory=list)

    def add_node(self, node: ProvenanceNode) -> None:
        if any(n.id == node.id for n in self.nodes):
            return
        self.nodes.append(node)

    def add_edge(self, edge: ProvenanceEdge) -> None:
        self.edges.append(edge)

    def node_map(self) -> dict[str, ProvenanceNode]:
        return {n.id: n for n in self.nodes}

    def why(self, node_id: str) -> list[ProvenanceNode]:
        """Walk backward along derived_from edges until sources."""
        by_dst: dict[str, list[str]] = {}
        for e in self.edges:
            by_dst.setdefault(e.dst, []).append(e.src)
        seen: set[str] = set()
        order: list[str] = []

        def walk(nid: str) -> None:
            if nid in seen:
                return
            seen.add(nid)
            order.append(nid)
            for parent in by_dst.get(nid, []):
                walk(parent)

        walk(node_id)
        nodes = self.node_map()
        return [nodes[i] for i in order if i in nodes]

    def sources_for(self, node_id: str) -> list[ProvenanceNode]:
        return [n for n in self.why(node_id) if n.type == "source"]


def assert_kind(expected: ProvenanceKind, actual: ProvenanceKind, *, context: str) -> None:
    if expected != actual:
        raise ProvenanceError(
            f"provenance kind mismatch in {context}: expected {expected.value}, got {actual.value}"
        )


def reject_simulated_as_observed(kind: ProvenanceKind, *, context: str = "ingest") -> None:
    if kind == ProvenanceKind.SIMULATED:
        raise ProvenanceError(
            f"simulated data cannot be ingested as observed ({context}). "
            "OBSERVED / DERIVED / FORECAST / SIMULATED are never mixed."
        )
    if kind != ProvenanceKind.OBSERVED:
        raise ProvenanceError(
            f"ingest channel is OBSERVED but event kind is {kind.value} ({context})"
        )
