"""
Manual Depth-First Search over ``reverse_adj`` — upstream candidate tracing.

From a flagged station, DFS walks *against* the flow (v -> its upstream neighbours)
and explores one tributary branch fully before backtracking. This naturally yields
the distinct root-to-headwater branch paths, which is what an investigator needs:
"which upstream reaches feed this station, and through which stations?"

Implementation is iterative (explicit stack) to avoid Python's recursion limit on
long river chains. Every vertex is pushed/expanded at most once (``visited`` set),
so time is O(V + E) and auxiliary space O(V).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DFS_CAVEATS = [
    "Upstream stations are *candidates for investigation*, not proven sources.",
    "Only monitored stations snapped to HydroRIVERS reaches are linked; unmonitored "
    "inflows (drains, industrial outfalls, lakes, unsnapped stations) are invisible to the graph.",
    "Edges follow HydroRIVERS NEXT_DOWN topology; a 1.5 km snap may attach a station to a "
    "nearby tributary instead of the main stem.",
    "Sampling dates differ between stations, so concentrations are not simultaneous.",
]


def dfs_upstream(graph, source: str, max_depth: Optional[int] = None) -> Dict[str, Any]:
    """Trace upstream candidates from ``source``.

    Result keys
    -----------
    candidates       : upstream stations in DFS discovery order (source excluded)
    traversal_order  : full DFS pre-order including the source
    depth            : {station_id: hops upstream from source}
    branch_paths     : list of paths [source, ..., headwater] — one per leaf branch
    parent           : DFS-tree parent pointers (for path reconstruction)
    caveats          : scientific limitations to display alongside results
    """
    if source not in graph.vertices:
        raise KeyError(f"Unknown vertex: {source}")

    visited = {source}
    depth = {source: 0}
    parent: Dict[str, Optional[str]] = {source: None}
    order: List[str] = []
    branch_paths: List[List[str]] = []
    stack = [source]

    while stack:
        u = stack.pop()                    # LIFO => depth-first
        order.append(u)
        children = []
        if max_depth is None or depth[u] < max_depth:
            # reversed() so the first-listed upstream neighbour is explored first
            for w in reversed(graph.reverse_adj[u]):
                if w not in visited:
                    visited.add(w)
                    depth[w] = depth[u] + 1
                    parent[w] = u
                    children.append(w)
                    stack.append(w)
        if not children and u != source:
            branch_paths.append(_path_to_root(parent, u))   # u is a headwater / branch end

    return {
        "source": source,
        "candidates": order[1:],
        "candidate_count": len(order) - 1,
        "traversal_order": order,
        "depth": depth,
        "parent": parent,
        "branch_paths": branch_paths,
        "branch_count": len(branch_paths),
        "caveats": list(DFS_CAVEATS),
        "complexity": "O(V + E) time, O(V) auxiliary space",
    }


def dfs_recursive_upstream(graph, source: str) -> List[str]:
    """Recursive variant (pre-order) kept for teaching/comparison; same O(V + E)."""
    if source not in graph.vertices:
        raise KeyError(f"Unknown vertex: {source}")
    visited, order = set(), []

    def visit(u: str) -> None:
        visited.add(u)
        order.append(u)
        for w in graph.reverse_adj[u]:
            if w not in visited:
                visit(w)

    visit(source)
    return order[1:]


def _path_to_root(parent: Dict[str, Optional[str]], leaf: str) -> List[str]:
    path = []
    node: Optional[str] = leaf
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()          # source ... leaf (walking upstream)
    return path
