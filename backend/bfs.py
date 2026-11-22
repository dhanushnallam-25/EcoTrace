"""
Manual Breadth-First Search over ``forward_adj`` — downstream impact analysis.

Starting at a flagged station, BFS visits stations level by level following the
direction of flow. ``level[v]`` = number of river hops (station-to-station edges)
from the source. Each vertex is enqueued at most once (``visited`` set) and each
edge is examined once, so the running time is O(V + E) and extra space is O(V).
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple


def bfs_downstream(graph, source: str, max_depth: Optional[int] = None) -> Dict[str, Any]:
    """Return every station reachable downstream of ``source``.

    Result keys
    -----------
    visited_order   : stations in BFS order (source first)
    levels          : {station_id: hop distance from source}
    traversal_edges : BFS-tree edges (u, v) in discovery order
    affected        : downstream stations (visited minus the source)
    affected_count  : len(affected)
    """
    if source not in graph.vertices:
        raise KeyError(f"Unknown vertex: {source}")

    visited = {source}
    levels: Dict[str, int] = {source: 0}
    order: List[str] = []
    tree_edges: List[Tuple[str, str]] = []
    queue = deque([source])

    while queue:
        u = queue.popleft()               # O(1) — why deque, not list.pop(0) (O(n))
        order.append(u)
        if max_depth is not None and levels[u] >= max_depth:
            continue
        for v in graph.forward_adj[u]:    # each edge examined once overall
            if v not in visited:          # O(1) set membership; also makes cycles safe
                visited.add(v)
                levels[v] = levels[u] + 1
                tree_edges.append((u, v))
                queue.append(v)

    affected = order[1:]
    return {
        "source": source,
        "visited_order": order,
        "levels": levels,
        "traversal_edges": tree_edges,
        "affected": affected,
        "affected_count": len(affected),
        "max_level": max(levels.values()) if levels else 0,
        "complexity": "O(V + E) time, O(V) auxiliary space",
    }


def bfs_on_matrix(order: List[str], matrix: List[List[int]], source: str) -> List[str]:
    """BFS on a dense adjacency matrix — O(V^2) because each row is fully scanned.

    Used only by the benchmark to contrast with the adjacency-list version.
    """
    index = {sid: i for i, sid in enumerate(order)}
    if source not in index:
        raise KeyError(f"Unknown vertex: {source}")
    n = len(order)
    start = index[source]
    seen = [False] * n
    seen[start] = True
    queue = deque([start])
    out = []
    while queue:
        i = queue.popleft()
        out.append(order[i])
        row = matrix[i]
        for j in range(n):                # full row scan = O(V) per vertex
            if row[j] and not seen[j]:
                seen[j] = True
                queue.append(j)
    return out
