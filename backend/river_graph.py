"""
DirectedRiverGraph — a hand-written directed graph built on Python dict adjacency lists.

Design (DSA rationale)
----------------------
* ``forward_adj[u]``  -> list of vertices ``v`` such that water flows u -> v (downstream).
* ``reverse_adj[v]``  -> list of vertices ``u`` such that u -> v (i.e. v's upstream neighbours).
* ``_edge_set``       -> set of (u, v) tuples for O(1) duplicate-edge detection.
* ``vertices[v]``     -> metadata dict (station name, lat/lon, HydroRIVERS reach id, ...).

Keeping *both* adjacency directions doubles edge storage (still O(V + E)) but lets
BFS-downstream and DFS-upstream each run in O(V + E) without having to scan or
transpose the whole graph on every query.

No NetworkX is used anywhere for structure or traversal.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# Metadata keys every vertex carries (missing values default to None).
VERTEX_FIELDS = (
    "station_id", "station_name", "lat", "lon", "river_name", "hyriv_id",
    "main_riv", "dist_dn_km", "match_status", "measurements",
)


class DirectedRiverGraph:
    """Directed graph of monitoring stations; an edge u -> v means v is downstream of u."""

    def __init__(self) -> None:
        self.forward_adj: Dict[str, List[str]] = {}
        self.reverse_adj: Dict[str, List[str]] = {}
        self.vertices: Dict[str, Dict[str, Any]] = {}
        self.edge_attrs: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._edge_set: set = set()

    # ------------------------------------------------------------------ vertices
    def add_vertex(self, station_id: str, **metadata: Any) -> bool:
        """Add a vertex (O(1)). Returns False (and merges metadata) if it already exists."""
        if station_id is None or str(station_id).strip() == "":
            raise ValueError("station_id must be a non-empty string")
        station_id = str(station_id)
        if station_id in self.vertices:
            self.vertices[station_id].update({k: v for k, v in metadata.items()})
            return False
        record = {field: None for field in VERTEX_FIELDS}
        record.update(metadata)
        record["station_id"] = station_id
        self.vertices[station_id] = record
        self.forward_adj[station_id] = []
        self.reverse_adj[station_id] = []
        return True

    def has_vertex(self, station_id: str) -> bool:
        return station_id in self.vertices

    def remove_vertex(self, station_id: str) -> bool:
        """Remove a vertex and all incident edges. O(deg(v) * avg_deg) using both adjacency lists."""
        if station_id not in self.vertices:
            return False
        for v in list(self.forward_adj[station_id]):
            self.remove_edge(station_id, v)
        for u in list(self.reverse_adj[station_id]):
            self.remove_edge(u, station_id)
        del self.forward_adj[station_id]
        del self.reverse_adj[station_id]
        del self.vertices[station_id]
        return True

    # --------------------------------------------------------------------- edges
    def add_edge(self, u: str, v: str, **attrs: Any) -> bool:
        """Add directed edge u -> v (O(1) average). Duplicate edges and self-loops are rejected."""
        if u not in self.vertices or v not in self.vertices:
            missing = u if u not in self.vertices else v
            raise KeyError(f"Unknown vertex: {missing}")
        if u == v:
            return False
        if (u, v) in self._edge_set:
            return False
        self._edge_set.add((u, v))
        self.forward_adj[u].append(v)
        self.reverse_adj[v].append(u)
        self.edge_attrs[(u, v)] = dict(attrs)
        return True

    def remove_edge(self, u: str, v: str) -> bool:
        if (u, v) not in self._edge_set:
            return False
        self._edge_set.discard((u, v))
        self.forward_adj[u].remove(v)
        self.reverse_adj[v].remove(u)
        self.edge_attrs.pop((u, v), None)
        return True

    def has_edge(self, u: str, v: str) -> bool:
        return (u, v) in self._edge_set

    # ----------------------------------------------------------------- queries
    def get_neighbors(self, station_id: str) -> List[str]:
        """Default neighbours = downstream neighbours (direction of flow)."""
        return self.get_downstream_neighbors(station_id)

    def get_downstream_neighbors(self, station_id: str) -> List[str]:
        self._require(station_id)
        return list(self.forward_adj[station_id])

    def get_upstream_neighbors(self, station_id: str) -> List[str]:
        self._require(station_id)
        return list(self.reverse_adj[station_id])

    def in_degree(self, station_id: str) -> int:
        self._require(station_id)
        return len(self.reverse_adj[station_id])

    def out_degree(self, station_id: str) -> int:
        self._require(station_id)
        return len(self.forward_adj[station_id])

    def is_isolated(self, station_id: str) -> bool:
        return self.in_degree(station_id) == 0 and self.out_degree(station_id) == 0

    def get_vertex(self, station_id: str) -> Dict[str, Any]:
        self._require(station_id)
        return self.vertices[station_id]

    def get_vertex_count(self) -> int:
        return len(self.vertices)

    def get_edge_count(self) -> int:
        return len(self._edge_set)

    def edges(self) -> Iterable[Tuple[str, str]]:
        for u, nbrs in self.forward_adj.items():
            for v in nbrs:
                yield (u, v)

    def connected_vertices(self) -> List[str]:
        return [v for v in self.vertices if not self.is_isolated(v)]

    def display_graph(self, include_isolated: bool = False, limit: Optional[int] = None) -> str:
        """Human-readable adjacency-list dump (used in the UI and viva demos)."""
        lines = []
        for sid in self.vertices:
            if not include_isolated and self.is_isolated(sid):
                continue
            name = self.vertices[sid].get("station_name") or sid
            down = ", ".join(self.forward_adj[sid]) or "∅"
            up = ", ".join(self.reverse_adj[sid]) or "∅"
            lines.append(f"{sid} [{name}]  -> downstream: {down} | upstream: {up}")
            if limit is not None and len(lines) >= limit:
                lines.append("...")
                break
        return "\n".join(lines) if lines else "(graph has no connected vertices)"

    def to_adjacency_matrix(self) -> Tuple[List[str], List[List[int]]]:
        """Dense V x V matrix — used only by the benchmark to contrast O(V^2) memory."""
        order = list(self.vertices)
        index = {sid: i for i, sid in enumerate(order)}
        n = len(order)
        matrix = [[0] * n for _ in range(n)]
        for u, v in self.edges():
            matrix[index[u]][index[v]] = 1
        return order, matrix

    def _require(self, station_id: str) -> None:
        if station_id not in self.vertices:
            raise KeyError(f"Unknown vertex: {station_id}")

    def __contains__(self, station_id: object) -> bool:
        return station_id in self.vertices

    def __len__(self) -> int:
        return len(self.vertices)

    def __repr__(self) -> str:
        return f"DirectedRiverGraph(V={self.get_vertex_count()}, E={self.get_edge_count()})"
