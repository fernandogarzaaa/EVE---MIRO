"""On-disk local graph memory.

Used when MIROFISH_MEMORY=local (or EVE_MIRO_ALLOW_LOCAL_MEMORY=1) and no
ZEP_API_KEY is configured. This is a real JSON graph on disk — not a Zep
Cloud client, not a silent fake, and not a stub that pretends Cloud ran.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import Config
from .zep_entity_reader import EntityNode, FilteredEntities

_LOCK = threading.Lock()

_STOPWORDS = {
    "The",
    "A",
    "An",
    "This",
    "That",
    "These",
    "Those",
    "In",
    "On",
    "At",
    "For",
    "And",
    "Or",
    "But",
    "If",
    "When",
    "With",
    "From",
    "To",
    "Of",
    "By",
    "As",
    "It",
    "Its",
    "He",
    "She",
    "They",
    "We",
    "You",
}


def local_graphs_dir() -> str:
    return os.path.join(Config.UPLOAD_FOLDER, "local_graphs")


def should_use_local_graph(graph_id: str | None = None) -> bool:
    """True when local on-disk memory should serve this graph."""
    if Config.use_local_graph_memory():
        return True
    if graph_id and str(graph_id).startswith("local_"):
        return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(graph_id: str) -> str:
    if not graph_id or not re.fullmatch(r"[A-Za-z0-9_-]+", graph_id):
        raise ValueError(f"Invalid graph_id: {graph_id!r}")
    return graph_id


def _candidates_from_text(text: str) -> List[str]:
    """Deterministic proper-noun / acronym candidates so tests stay offline."""
    names: List[str] = []
    if not text:
        return names
    for match in re.finditer(r'"([^"]{2,80})"', text):
        names.append(match.group(1).strip())
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        names.append(match.group(1).strip())
    for match in re.finditer(r"\b([A-Z]{2,}(?:/[A-Z]+)?)\b", text):
        names.append(match.group(1).strip())
    seen: set[str] = set()
    out: List[str] = []
    for name in names:
        key = name.lower()
        if key in seen or name in _STOPWORDS:
            continue
        seen.add(key)
        out.append(name)
    return out


def _summary_for(text: str, name: str, fallback: str) -> str:
    if text and name:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if name.lower() in sentence.lower():
                return sentence.strip()[:500]
    snippet = (text or "").strip().replace("\n", " ")
    if snippet:
        return snippet[:500]
    return fallback


def derive_nodes_and_edges(
    ontology: Dict[str, Any] | None,
    chunks: List[str],
    graph_id: str,
    graph_name: str = "",
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build nodes/edges from ontology entity_types + seed text.

    Deterministic (no LLM) so pytest stays offline. Each entity type gets at
    least one node with a custom label so filter_defined_entities keeps it.
    """
    ontology = ontology or {}
    text = "\n".join(chunks or [])
    entity_types = list(ontology.get("entity_types") or [])
    edge_types = list(ontology.get("edge_types") or [])
    candidates = _candidates_from_text(text)
    created = _now()

    nodes: List[Dict[str, Any]] = []
    if entity_types:
        for index, entity_def in enumerate(entity_types):
            if not isinstance(entity_def, dict):
                type_name = str(entity_def)
                description = f"A {type_name} entity."
            else:
                type_name = str(entity_def.get("name") or f"Entity{index + 1}")
                description = str(entity_def.get("description") or f"A {type_name} entity.")
            if index < len(candidates):
                node_name = candidates[index]
            else:
                node_name = f"{type_name} {index + 1}"
            nodes.append(
                {
                    "uuid": f"{graph_id}-n{index}-{uuid.uuid4().hex[:8]}",
                    "name": node_name,
                    "labels": ["Entity", type_name],
                    "summary": _summary_for(text, node_name, description),
                    "attributes": {},
                    "created_at": created,
                }
            )
    if not nodes:
        fallback_name = candidates[0] if candidates else (graph_name or "Local Entity")
        nodes.append(
            {
                "uuid": f"{graph_id}-n0-{uuid.uuid4().hex[:8]}",
                "name": fallback_name,
                "labels": ["Entity", "Agent"],
                "summary": _summary_for(text, fallback_name, "Seed entity from local graph text."),
                "attributes": {},
                "created_at": created,
            }
        )

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        for label in node.get("labels") or []:
            if label not in {"Entity", "Node"}:
                by_type.setdefault(label, []).append(node)

    edges: List[Dict[str, Any]] = []
    for index, edge_def in enumerate(edge_types):
        if not isinstance(edge_def, dict):
            edge_name = str(edge_def)
            source_targets: List[Dict[str, Any]] = []
        else:
            edge_name = str(edge_def.get("name") or "RELATED_TO")
            source_targets = list(edge_def.get("source_targets") or [])
        source = nodes[index % len(nodes)]
        target = nodes[(index + 1) % len(nodes)]
        if source_targets:
            pair = source_targets[0] if isinstance(source_targets[0], dict) else {}
            source_type = pair.get("source")
            target_type = pair.get("target")
            if source_type and by_type.get(source_type):
                source = by_type[source_type][0]
            if target_type and by_type.get(target_type):
                target_candidates = by_type[target_type]
                target = next((n for n in target_candidates if n["uuid"] != source["uuid"]), target_candidates[0])
        if source["uuid"] == target["uuid"] and len(nodes) > 1:
            target = nodes[(nodes.index(source) + 1) % len(nodes)]
        edges.append(
            {
                "uuid": f"{graph_id}-e{index}-{uuid.uuid4().hex[:8]}",
                "name": edge_name,
                "fact": f"{source['name']} {edge_name} {target['name']}",
                "fact_type": edge_name,
                "source_node_uuid": source["uuid"],
                "target_node_uuid": target["uuid"],
                "source_node_name": source["name"],
                "target_node_name": target["name"],
                "attributes": {},
                "created_at": created,
                "valid_at": created,
                "invalid_at": None,
                "expired_at": None,
                "episodes": [],
            }
        )
    return nodes, edges


class LocalGraphStore:
    """JSON files under uploads/local_graphs/<graph_id>.json."""

    @classmethod
    def _path(cls, graph_id: str) -> str:
        os.makedirs(local_graphs_dir(), exist_ok=True)
        return os.path.join(local_graphs_dir(), f"{_safe_id(graph_id)}.json")

    @classmethod
    def exists(cls, graph_id: str | None) -> bool:
        if not graph_id:
            return False
        try:
            return os.path.isfile(cls._path(graph_id))
        except ValueError:
            return False

    @classmethod
    def load(cls, graph_id: str) -> Dict[str, Any]:
        path = cls._path(graph_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Local graph not found: {graph_id}")
        with _LOCK:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)

    @classmethod
    def save(cls, record: Dict[str, Any]) -> None:
        graph_id = record["graph_id"]
        path = cls._path(graph_id)
        record["updated_at"] = _now()
        tmp_path = f"{path}.tmp"
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)

    @classmethod
    def create(cls, graph_id: str, name: str) -> Dict[str, Any]:
        record = {
            "graph_id": graph_id,
            "name": name,
            "backend": "local_disk",
            "not_zep_cloud": True,
            "ontology": {},
            "chunks": [],
            "nodes": [],
            "edges": [],
            "status": "created",
            "created_at": _now(),
            "updated_at": _now(),
        }
        cls.save(record)
        return record

    @classmethod
    def set_ontology(cls, graph_id: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        record = cls.load(graph_id)
        record["ontology"] = ontology or {}
        cls.save(record)
        return record

    @classmethod
    def add_chunks(cls, graph_id: str, chunks: List[str]) -> Dict[str, Any]:
        record = cls.load(graph_id)
        record["chunks"] = list(chunks or [])
        nodes, edges = derive_nodes_and_edges(
            record.get("ontology") or {},
            record["chunks"],
            graph_id,
            record.get("name") or "",
        )
        record["nodes"] = nodes
        record["edges"] = edges
        record["status"] = "complete"
        cls.save(record)
        return record

    @classmethod
    def delete(cls, graph_id: str) -> None:
        if not graph_id:
            return
        try:
            path = cls._path(graph_id)
        except ValueError:
            return
        with _LOCK:
            if os.path.isfile(path):
                os.remove(path)

    @classmethod
    def get_graph_data(cls, graph_id: str) -> Dict[str, Any]:
        record = cls.load(graph_id)
        nodes = list(record.get("nodes") or [])
        edges = list(record.get("edges") or [])
        return {
            "graph_id": graph_id,
            "name": record.get("name") or "",
            "backend": "local_disk",
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    @classmethod
    def filter_defined_entities(
        cls,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        record = cls.load(graph_id)
        all_nodes = list(record.get("nodes") or [])
        all_edges = list(record.get("edges") or []) if enrich_with_edges else []
        node_map = {n.get("uuid"): n for n in all_nodes if n.get("uuid")}
        filtered: List[EntityNode] = []
        entity_types_found: set[str] = set()

        for node in all_nodes:
            labels = list(node.get("labels") or [])
            custom_labels = [label for label in labels if label not in {"Entity", "Node"}]
            if not custom_labels:
                continue
            if defined_entity_types:
                matching = [label for label in custom_labels if label in defined_entity_types]
                if not matching:
                    continue
                entity_type = matching[0]
            else:
                entity_type = custom_labels[0]
            entity_types_found.add(entity_type)
            entity = EntityNode(
                uuid=node.get("uuid") or "",
                name=node.get("name") or "",
                labels=labels,
                summary=node.get("summary") or "",
                attributes=node.get("attributes") or {},
            )
            if enrich_with_edges:
                related_edges = []
                related_uuids: set[str] = set()
                for edge in all_edges:
                    if edge.get("source_node_uuid") == entity.uuid:
                        related_edges.append(
                            {
                                "direction": "outgoing",
                                "edge_name": edge.get("name") or "",
                                "fact": edge.get("fact") or "",
                                "target_node_uuid": edge.get("target_node_uuid"),
                            }
                        )
                        if edge.get("target_node_uuid"):
                            related_uuids.add(edge["target_node_uuid"])
                    elif edge.get("target_node_uuid") == entity.uuid:
                        related_edges.append(
                            {
                                "direction": "incoming",
                                "edge_name": edge.get("name") or "",
                                "fact": edge.get("fact") or "",
                                "source_node_uuid": edge.get("source_node_uuid"),
                            }
                        )
                        if edge.get("source_node_uuid"):
                            related_uuids.add(edge["source_node_uuid"])
                entity.related_edges = related_edges
                entity.related_nodes = [
                    {
                        "uuid": related.get("uuid"),
                        "name": related.get("name") or "",
                        "labels": related.get("labels") or [],
                        "summary": related.get("summary") or "",
                    }
                    for related_uuid in related_uuids
                    if (related := node_map.get(related_uuid))
                ]
            filtered.append(entity)

        return FilteredEntities(
            entities=filtered,
            entity_types=entity_types_found,
            total_count=len(all_nodes),
            filtered_count=len(filtered),
        )


class LocalEntityReader:
    """ZepEntityReader-shaped reader backed by LocalGraphStore JSON."""

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        return LocalGraphStore.filter_defined_entities(
            graph_id,
            defined_entity_types=defined_entity_types,
            enrich_with_edges=enrich_with_edges,
        )

    def get_entity_with_context(self, graph_id: str, entity_uuid: str) -> Optional[EntityNode]:
        result = self.filter_defined_entities(graph_id, enrich_with_edges=True)
        for entity in result.entities:
            if entity.uuid == entity_uuid:
                return entity
        # Also return unlabeled nodes if requested by uuid.
        record = LocalGraphStore.load(graph_id)
        for node in record.get("nodes") or []:
            if node.get("uuid") == entity_uuid:
                return EntityNode(
                    uuid=node.get("uuid") or "",
                    name=node.get("name") or "",
                    labels=list(node.get("labels") or []),
                    summary=node.get("summary") or "",
                    attributes=node.get("attributes") or {},
                )
        return None

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True,
    ) -> List[EntityNode]:
        return self.filter_defined_entities(
            graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges,
        ).entities


def entity_reader_for(graph_id: str | None = None):
    """Local JSON reader or ZepEntityReader. Zep still fail-closes without a key."""
    if should_use_local_graph(graph_id):
        return LocalEntityReader()
    from .zep_entity_reader import ZepEntityReader

    return ZepEntityReader()
