"""DirectedRiverGraph: structure, reverse edges, duplicates, isolated lakes (SYNTHETIC data)."""
import pytest

from backend.river_graph import DirectedRiverGraph


def test_counts_and_forward_reverse_adjacency(chain_graph):
    g = chain_graph
    assert g.get_vertex_count() == 6
    assert g.get_edge_count() == 4
    assert g.get_downstream_neighbors("C") == ["D"]
    assert sorted(g.get_upstream_neighbors("C")) == ["A", "B"]
    assert g.get_neighbors("A") == ["C"]
    # every forward edge has its mirror in reverse_adj
    for u, v in g.edges():
        assert u in g.reverse_adj[v]


def test_isolated_lake_vertex(chain_graph):
    assert chain_graph.in_degree("E") == 0
    assert chain_graph.out_degree("E") == 0
    assert chain_graph.is_isolated("E")
    assert "E" not in chain_graph.connected_vertices()


def test_duplicate_edges_and_self_loops_rejected(chain_graph):
    assert chain_graph.add_edge("A", "C") is False
    assert chain_graph.add_edge("A", "A") is False
    assert chain_graph.get_edge_count() == 4
    assert chain_graph.forward_adj["A"].count("C") == 1


def test_duplicate_vertex_merges_metadata():
    g = DirectedRiverGraph()
    assert g.add_vertex("X", station_name="SYN-X") is True
    assert g.add_vertex("X", lat=12.0) is False
    assert g.get_vertex("X")["station_name"] == "SYN-X"
    assert g.get_vertex("X")["lat"] == 12.0
    assert g.get_vertex_count() == 1


def test_unknown_vertex_errors(chain_graph):
    with pytest.raises(KeyError):
        chain_graph.add_edge("A", "ZZZ")
    with pytest.raises(KeyError):
        chain_graph.get_upstream_neighbors("ZZZ")
    with pytest.raises(ValueError):
        chain_graph.add_vertex("")


def test_remove_vertex_cleans_both_directions(chain_graph):
    g = chain_graph
    assert g.remove_vertex("C") is True
    assert "C" not in g
    assert g.get_downstream_neighbors("A") == []
    assert g.get_upstream_neighbors("D") == []
    assert g.get_edge_count() == 1          # only D -> F remains
    assert g.remove_vertex("C") is False


def test_remove_edge(chain_graph):
    assert chain_graph.remove_edge("D", "F") is True
    assert not chain_graph.has_edge("D", "F")
    assert chain_graph.get_upstream_neighbors("F") == []
    assert chain_graph.remove_edge("D", "F") is False


def test_display_and_matrix(chain_graph):
    text = chain_graph.display_graph()
    assert "C [SYN-C]" in text and "E [" not in text           # isolated hidden by default
    assert "E [SYN-E]" in chain_graph.display_graph(include_isolated=True)
    order, m = chain_graph.to_adjacency_matrix()
    assert sum(map(sum, m)) == chain_graph.get_edge_count()
    assert m[order.index("A")][order.index("C")] == 1
