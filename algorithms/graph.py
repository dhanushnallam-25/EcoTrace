import collections
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

class RiverGraph:
    """Directed graph representing river flow.

    Stores adjacency list for downstream (source -> destinations) and
    reverse adjacency for upstream (destination -> sources).
    """

    def __init__(self) -> None:
        self.downstream: Dict[str, Set[str]] = defaultdict(set)
        self.upstream: Dict[str, Set[str]] = defaultdict(set)
        self.stations: Set[str] = set()

    def add_station(self, station_id: str) -> None:
        """Register a station identifier.

        Duplicate additions are ignored.
        """
        self.stations.add(station_id)
        # Ensure entries exist in adjacency dicts
        self.downstream.setdefault(station_id, set())
        self.upstream.setdefault(station_id, set())

    def add_connection(self, source: str, destination: str) -> None:
        """Add a directed edge source -> destination.

        The edge represents water flowing from *source* towards *destination*.
        Both stations are added automatically if they were not present.
        """
        self.add_station(source)
        self.add_station(destination)
        # Prevent duplicate edges
        if destination not in self.downstream[source]:
            self.downstream[source].add(destination)
            self.upstream[destination].add(source)

    def find_upstream(self, station_id: str) -> List[Tuple[str, int]]:
        """Return list of upstream stations with BFS distance.

        Parameters
        ----------
        station_id: str
            Target station for which upstream neighbours are sought.

        Returns
        -------
        List[Tuple[str, int]]
            Each tuple contains (upstream_station_id, distance) where
            distance is the number of edges from the upstream station to the
            target (i.e., BFS level). Results are sorted by distance then by
            station identifier for deterministic output.
        """
        if station_id not in self.stations:
            raise ValueError(f"Station '{station_id}' not found in graph")

        visited: Set[str] = set()
        results: List[Tuple[str, int]] = []
        queue: deque[Tuple[str, int]] = deque()
        # Start from immediate upstream stations (distance 1)
        for upstream_station in self.upstream.get(station_id, []):
            queue.append((upstream_station, 1))
            visited.add(upstream_station)

        while queue:
            current, dist = queue.popleft()
            # Exclude the original station if encountered via a cycle
            if current != station_id:
                results.append((current, dist))
            for nxt in self.upstream.get(current, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, dist + 1))

        # Sort for deterministic output
        results.sort(key=lambda x: (x[1], x[0]))
        return results
        """Return list of upstream stations with BFS distance.

        Parameters
        ----------
        station_id: str
            Target station for which upstream neighbours are sought.

        Returns
        -------
        List[Tuple[str, int]]
            Each tuple contains (upstream_station_id, distance) where
            distance is the number of edges from the upstream station to the
            target (i.e., BFS level). Results are sorted by distance then by
            station identifier for deterministic output.
        """
        if station_id not in self.stations:
            raise ValueError(f"Station '{station_id}' not found in graph")

        visited: Set[str] = set()
        results: List[Tuple[str, int]] = []
        queue: deque[Tuple[str, int]] = deque()
        # Start from immediate upstream stations (distance 1)
        for upstream_station in self.upstream.get(station_id, []):
            queue.append((upstream_station, 1))
            visited.add(upstream_station)

        while queue:
            current, dist = queue.popleft()
            results.append((current, dist))
            # Enqueue further upstream neighbours
            for nxt in self.upstream.get(current, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, dist + 1))

        # Sort for deterministic output
        results.sort(key=lambda x: (x[1], x[0]))
        return results

    def find_downstream(self, station_id: str) -> List[Tuple[str, int]]:
        """Return downstream stations using BFS (optional helper)."""
        if station_id not in self.stations:
            raise ValueError(f"Station '{station_id}' not found in graph")
        visited: Set[str] = set()
        results: List[Tuple[str, int]] = []
        queue: deque[Tuple[str, int]] = deque()
        for dst in self.downstream.get(station_id, []):
            queue.append((dst, 1))
            visited.add(dst)
        while queue:
            cur, d = queue.popleft()
            results.append((cur, d))
            for nxt in self.downstream.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, d + 1))
        results.sort(key=lambda x: (x[1], x[0]))
        return results
