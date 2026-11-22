"""DFS upstream tracing (SYNTHETIC graphs)."""
import pytest

from backend.dfs import dfs_recursive_upstream, dfs_upstream
from backend.river_graph import DirectedRiverGraph


def test_dfs_upstream_candidates_and_depth(chain_graph):
    res = dfs_upstream(chain_graph, "D")
    assert set(res["candidates"]) == {"A", "B", "C"}
    assert res["depth"] == {"D": 0, "C": 1, "A": 2, "B": 2}
    assert res["traversal_order"][0] == "D"
    assert res["traversal_order"][1] == "C"       # depth-first: C before its parents


def test_dfs_branch_paths(chain_graph):
    res = dfs_upstream(chain_graph, "F")
    paths = sorted(res["branch_paths"])
    assert paths == [["F", "D", "C", "A"], ["F", "D", "C", "B"]]
    assert res["branch_count"] == 2


def test_dfs_headwater_and_isolated(chain_graph):
    assert dfs_upstream(chain_graph, "A")["candidates"] == []
    assert dfs_upstream(chain_graph, "E")["branch_paths"] == []


def test_dfs_cycle_safe():
    g = DirectedRiverGraph()
    for v in "PQR":
        g.add_vertex(v)
    g.add_edge("P", "Q")
    g.add_edge("Q", "R")
    g.add_edge("R", "P")
    assert set(dfs_upstream(g, "P")["candidates"]) == {"Q", "R"}


def test_dfs_caveats_present(chain_graph):
    res = dfs_upstream(chain_graph, "D")
    assert any("not proven sources" in c for c in res["caveats"])


def test_recursive_matches_iterative_set(chain_graph):
    assert set(dfs_recursive_upstream(chain_graph, "F")) == set(dfs_upstream(chain_graph, "F")["candidates"])


def test_dfs_unknown_vertex(chain_graph):
    with pytest.raises(KeyError):
        dfs_upstream(chain_graph, "NOPE")


def test_dfs_deep_chain_no_recursion_error():
    g = DirectedRiverGraph()
    n = 5000
    for i in range(n):
        g.add_vertex(f"V{i}")
    for i in range(n - 1):
        g.add_edge(f"V{i}", f"V{i + 1}")
    assert dfs_upstream(g, f"V{n - 1}")["candidate_count"] == n - 1
