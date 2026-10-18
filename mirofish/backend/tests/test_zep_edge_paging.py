from types import SimpleNamespace

import pytest

from app.utils import zep_paging


def _client(edges):
    calls = []

    class EdgeApi:
        def list(self, *args, **kwargs):
            calls.append((args, kwargs))
            return iter(edges)

    return SimpleNamespace(graph=SimpleNamespace(edge=EdgeApi())), calls


def test_edge_cap_stops_at_requested_max_items():
    edges = [SimpleNamespace(uuid_=f"e{index}") for index in range(1, 5)]
    client, calls = _client(edges)

    result = zep_paging.fetch_all_edges(client, "graph", page_size=2, max_items=3)

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert calls == [(("graph",), {"page_size": 2})]


def test_fetch_all_materializes_the_whole_pager():
    edges = [SimpleNamespace(uuid_=f"e{index}") for index in range(1, 4)]
    client, calls = _client(edges)

    result = zep_paging.fetch_all_edges(client, "graph", page_size=2)

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert calls == [(("graph",), {"page_size": 2})]


def test_fetch_all_nodes_calls_node_list_with_page_size():
    nodes = [SimpleNamespace(uuid_="n1")]
    calls = []

    class NodeApi:
        def list(self, *args, **kwargs):
            calls.append((args, kwargs))
            return iter(nodes)

    client = SimpleNamespace(graph=SimpleNamespace(node=NodeApi()))

    result = zep_paging.fetch_all_nodes(client, "graph", page_size=25)

    assert [node.uuid_ for node in result] == ["n1"]
    assert calls == [(("graph",), {"page_size": 25})]


def test_transient_pager_failure_is_retried(monkeypatch):
    edges = [SimpleNamespace(uuid_="e1")]
    attempts = []

    class EdgeApi:
        def list(self, *args, **kwargs):
            attempts.append(True)
            if len(attempts) == 1:
                raise TimeoutError("transient")
            return iter(edges)

    client = SimpleNamespace(graph=SimpleNamespace(edge=EdgeApi()))
    monkeypatch.setattr(zep_paging, "_DEFAULT_RETRY_DELAY", 0.0)

    result = zep_paging.fetch_all_edges(client, "graph", max_retries=2)

    assert [edge.uuid_ for edge in result] == ["e1"]
    assert len(attempts) == 2


def test_invalid_page_size_is_rejected():
    client, _calls = _client([])

    with pytest.raises(ValueError, match="page_size"):
        zep_paging.fetch_all_edges(client, "graph", page_size=0)
def test_max_items_of_one_is_accepted():
    edges = [SimpleNamespace(uuid_="e1"), SimpleNamespace(uuid_="e2")]
    client, _calls = _client(edges)

    result = zep_paging.fetch_all_edges(client, "graph", max_items=1)

    assert [edge.uuid_ for edge in result] == ["e1"]


def test_max_items_of_zero_is_rejected():
    client, _calls = _client([])

    with pytest.raises(ValueError, match="max_items"):
        zep_paging.fetch_all_edges(client, "graph", max_items=0)


def test_max_items_equal_to_result_size_does_not_truncate():
    edges = [SimpleNamespace(uuid_=f"e{index}") for index in range(1, 4)]
    client, _calls = _client(edges)

    result = zep_paging.fetch_all_edges(client, "graph", max_items=3)

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
