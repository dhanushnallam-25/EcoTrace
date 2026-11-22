"""BFS downstream traversal (SYNTHETIC graphs)."""
import pytest

from backend.bfs import bfs_downstream, bfs_on_matrix
from backend.complexity_benchmark import synthetic_river_forest
from backend.river_graph import DirectedRiverGraph


def test_bfs_levels_and_order(chain_graph):
    res = bfs_downstream(chain_graph, "A")
    assert res["visited_order"] == ["A", "C", "D", "F"]
    assert res["levels"] == {"A": 0, "C": 1, "D": 2, "F": 3}
    assert res["affected"] == ["C", "D", "F"]
    assert res["affected_count"] == 3
    assert res["traversal_edges"] == [("A", "C"), ("C", "D"), ("D", "F")]


def test_bfs_from_sink_and_isolated(chain_graph):
    assert bfs_downstream(chain_graph, "F")["affected_count"] == 0
    assert bfs_downstream(chain_graph, "E")["visited_order"] == ["E"]


def test_bfs_branching_and_shortest_hops():
    g = DirectedRiverGraph()
    for v in "SABCT":
        g.add_vertex(v)
    for u, v in [("S", "A"), ("S", "B"), ("A", "C"), ("B", "C"), ("C", "T"), ("S", "T")]:
        g.add_edge(u, v)
    res = bfs_downstream(g, "S")
    assert res["levels"]["T"] == 1               # BFS gives the minimum hop count
    assert res["levels"]["C"] == 2
    assert len(res["visited_order"]) == len(set(res["visited_order"])) == 5


def test_bfs_cycle_terminates():
    g = DirectedRiverGraph()
    for v in "XYZ":
        g.add_vertex(v)
    g.add_edge("X", "Y")
    g.add_edge("Y", "Z")
    g.add_edge("Z", "X")                         # cycle (not physical, but must be safe)
    assert bfs_downstream(g, "X")["visited_order"] == ["X", "Y", "Z"]


def test_bfs_max_depth(chain_graph):
    assert bfs_downstream(chain_graph, "A", max_depth=1)["affected"] == ["C"]


def test_bfs_unknown_vertex(chain_graph):
    with pytest.raises(KeyError):
        bfs_downstream(chain_graph, "NOPE")


def test_list_and_matrix_bfs_agree():
    g = synthetic_river_forest(200, seed=3, extra_edge_ratio=0.3)
    order, m = g.to_adjacency_matrix()
    for src in ("S150", "S7", "S199"):
        assert set(bfs_downstream(g, src)["visited_order"]) == set(bfs_on_matrix(order, m, src))
