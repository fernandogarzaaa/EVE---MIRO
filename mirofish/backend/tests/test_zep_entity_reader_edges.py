from types import SimpleNamespace

from zep_cloud.graph.node.client import NodeClient

from app.services.zep_entity_reader import ZepEntityReader


def test_pinned_zep_sdk_removed_unscoped_node_access():
    # zep-cloud 4.0 has no unscoped node reads; every node call is graph-scoped.
    assert hasattr(NodeClient, "get")
    assert hasattr(NodeClient, "list_neighbors")
    assert not hasattr(NodeClient, "get_edges")


def test_get_node_edges_filters_the_full_graph_both_directions():
    incoming = {
        "uuid": "edge-in",
        "name": "WORKS_AT",
        "fact": "Alice works at Acme",
        "source_node_uuid": "alice",
        "target_node_uuid": "acme",
    }
    outgoing = {
        "uuid": "edge-out",
        "name": "BUILDS",
        "fact": "Acme builds Product",
        "source_node_uuid": "acme",
        "target_node_uuid": "product",
    }
    unrelated = {
        "uuid": "edge-unrelated",
        "name": "LOCATED_IN",
        "fact": "OtherCo is located in Paris",
        "source_node_uuid": "other-company",
        "target_node_uuid": "paris",
    }
    seen = []

    reader = object.__new__(ZepEntityReader)
    reader.get_all_edges = lambda graph_id: seen.append(graph_id) or [incoming, outgoing, unrelated]

    result = reader.get_node_edges("acme", graph_id="graph-id")

    assert result == [incoming, outgoing]
    assert seen == ["graph-id"]


def test_get_node_edges_requires_a_graph_id():
    reader = object.__new__(ZepEntityReader)
    reader.get_all_edges = lambda graph_id: []

    try:
        reader.get_node_edges("node-1")
    except TypeError:
        return
    raise AssertionError("get_node_edges must require graph_id")


def test_node_detail_reads_use_the_graph_scoped_sdk_call():
    edge = SimpleNamespace(
        uuid_="edge-1",
        name="KNOWS",
        fact="Alice knows Bob",
        source_node_uuid="node-1",
        target_node_uuid="node-2",
        attributes={"since": "2024"},
    )
    calls = []

    class NodeApi:
        def list_neighbors(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [SimpleNamespace(edges=[edge], node=SimpleNamespace(uuid_="node-2"))]

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(graph=SimpleNamespace(node=NodeApi()))

    neighbors = list(reader.client.graph.node.list_neighbors("graph-id", "node-1"))

    assert calls == [(("graph-id", "node-1"), {})]
    assert [entry.edges[0].uuid_ for entry in neighbors] == ["edge-1"]
