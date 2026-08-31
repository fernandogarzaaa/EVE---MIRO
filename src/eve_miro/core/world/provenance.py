"""Provenance graph: conclusions → experiences → states → events → sources."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eve_miro.core.world.events import ProvenanceKind
from eve_miro.errors import ProvenanceError

NodeType = Literal["source", "event", "state", "experience", "conclusion", "simulation", "episode"]


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

    def trace(self, conclusion_id: str) -> list[ProvenanceNode]:
        """Answer 'why' for a conclusion: episode, world state, events, source providers."""
        return self.why(conclusion_id)

    def sources_for(self, node_id: str) -> list[ProvenanceNode]:
        return [n for n in self.why(node_id) if n.type == "source"]


def trace(conclusion_id: str, graph: ProvenanceGraph) -> list[ProvenanceNode]:
    """Module-level helper: trace(conclusion_id) via a provenance graph."""
    return graph.trace(conclusion_id)


def conclusion_graph(
    conclusion_id: str,
    *,
    label: str = "conclusion",
    experience_id: str | None = None,
    episode_id: str | None = None,
    world_state_timestamp: str | None = None,
    world_id: str | None = None,
    event_ids: list[str] | None = None,
    source_providers: list[str] | None = None,
    simulation_id: str | None = None,
    kind: ProvenanceKind = ProvenanceKind.DERIVED,
) -> ProvenanceGraph:
    """Build a why-graph: conclusion ← experience/simulation ← state ← events ← sources."""
    graph = ProvenanceGraph()
    graph.add_node(ProvenanceNode(id=conclusion_id, type="conclusion", label=label, provenance_kind=kind))
    cursor = conclusion_id

    if experience_id:
        graph.add_node(
            ProvenanceNode(
                id=f"experience:{experience_id}",
                type="experience",
                label=experience_id,
                provenance_kind=ProvenanceKind.SIMULATED,
            )
        )
        graph.add_edge(ProvenanceEdge(src=f"experience:{experience_id}", dst=cursor, rel="derived_from"))
        cursor = f"experience:{experience_id}"

    if simulation_id:
        sim_nid = f"simulation:{simulation_id}"
        graph.add_node(
            ProvenanceNode(id=sim_nid, type="simulation", label=simulation_id, provenance_kind=ProvenanceKind.SIMULATED)
        )
        graph.add_edge(ProvenanceEdge(src=sim_nid, dst=cursor, rel="derived_from"))
        cursor = sim_nid

    if episode_id:
        ep_nid = f"episode:{episode_id}"
        graph.add_node(ProvenanceNode(id=ep_nid, type="episode", label=episode_id, provenance_kind=ProvenanceKind.SIMULATED))
        graph.add_edge(ProvenanceEdge(src=ep_nid, dst=cursor, rel="derived_from"))

    state_nid = None
    if world_state_timestamp is not None:
        wid = world_id or "world"
        state_nid = f"state:{wid}:{world_state_timestamp}"
        graph.add_node(
            ProvenanceNode(
                id=state_nid,
                type="state",
                label=f"WorldState@ {world_state_timestamp}",
                provenance_kind=ProvenanceKind.DERIVED,
            )
        )
        graph.add_edge(ProvenanceEdge(src=state_nid, dst=cursor, rel="derived_from"))

    for eid in event_ids or []:
        ev_nid = eid if eid.startswith("event:") else f"event:{eid}"
        graph.add_node(ProvenanceNode(id=ev_nid, type="event", label=eid, provenance_kind=ProvenanceKind.OBSERVED))
        dst = state_nid or cursor
        graph.add_edge(ProvenanceEdge(src=ev_nid, dst=dst, rel="folded_into"))
        for provider in source_providers or []:
            src_nid = f"source:{provider}"
            graph.add_node(
                ProvenanceNode(
                    id=src_nid, type="source", label=provider, provenance_kind=ProvenanceKind.OBSERVED
                )
            )
            graph.add_edge(ProvenanceEdge(src=src_nid, dst=ev_nid, rel="emitted"))

    if not (event_ids or []) and source_providers:
        for provider in source_providers:
            src_nid = f"source:{provider}"
            graph.add_node(
                ProvenanceNode(id=src_nid, type="source", label=provider, provenance_kind=ProvenanceKind.OBSERVED)
            )
            graph.add_edge(ProvenanceEdge(src=src_nid, dst=state_nid or cursor, rel="emitted"))

    return graph


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
