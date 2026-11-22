"""
Custom array-backed binary Max Heap (no ``heapq``) for incident prioritisation.

Layout: ``_heap`` is a Python list; for index i, children are 2i+1 and 2i+2 and the
parent is (i-1)//2. Invariant: heap[parent].priority_score >= heap[child].priority_score.

``_index`` maps incident_id -> array position so ``update_priority`` can locate an
item in O(1) and then restore the invariant in O(log n) — the classic "indexed
priority queue". Ties are broken by insertion sequence (earlier first) so the order
is deterministic.

Complexities: insert O(log n), extract_max O(log n), peek O(1),
heapify O(n) (bottom-up), update_priority O(log n).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


class MaxHeap:
    def __init__(self, items: Optional[Iterable[Dict[str, Any]]] = None) -> None:
        self._heap: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}
        self._seq = 0
        if items:
            self.heapify(items)

    # ---------------------------------------------------------------- helpers
    def _key(self, i: int):
        item = self._heap[i]
        # Higher score first; earlier sequence wins ties (hence the negation).
        return (item["priority_score"], -item["_seq"])

    def _swap(self, i: int, j: int) -> None:
        h = self._heap
        h[i], h[j] = h[j], h[i]
        self._index[h[i]["incident_id"]] = i
        self._index[h[j]["incident_id"]] = j

    def _sift_up(self, i: int) -> None:
        while i > 0:
            parent = (i - 1) // 2
            if self._key(i) > self._key(parent):
                self._swap(i, parent)
                i = parent
            else:
                break

    def _sift_down(self, i: int) -> None:
        n = len(self._heap)
        while True:
            left, right, largest = 2 * i + 1, 2 * i + 2, i
            if left < n and self._key(left) > self._key(largest):
                largest = left
            if right < n and self._key(right) > self._key(largest):
                largest = right
            if largest == i:
                break
            self._swap(i, largest)
            i = largest

    def _prepare(self, item: Dict[str, Any]) -> Dict[str, Any]:
        if "incident_id" not in item or "priority_score" not in item:
            raise ValueError("Heap items need 'incident_id' and 'priority_score'")
        item = dict(item)
        item["priority_score"] = float(item["priority_score"])
        item["_seq"] = self._seq
        self._seq += 1
        return item

    # ------------------------------------------------------------- public API
    def insert(self, item: Dict[str, Any]) -> None:
        """Append at the end, then sift up. O(log n)."""
        if item.get("incident_id") in self._index:
            raise ValueError(f"Duplicate incident_id: {item['incident_id']}")
        item = self._prepare(item)
        self._heap.append(item)
        self._index[item["incident_id"]] = len(self._heap) - 1
        self._sift_up(len(self._heap) - 1)

    def peek(self) -> Optional[Dict[str, Any]]:
        """Highest-priority incident without removal. O(1)."""
        return self._public(self._heap[0]) if self._heap else None

    def extract_max(self) -> Optional[Dict[str, Any]]:
        """Remove and return the root; move last leaf to root and sift down. O(log n)."""
        if not self._heap:
            return None
        root = self._heap[0]
        last = self._heap.pop()
        del self._index[root["incident_id"]]
        if self._heap:
            self._heap[0] = last
            self._index[last["incident_id"]] = 0
            self._sift_down(0)
        return self._public(root)

    def heapify(self, items: Iterable[Dict[str, Any]]) -> None:
        """Build a heap from scratch bottom-up (Floyd). O(n) — cheaper than n inserts."""
        self._heap, self._index, self._seq = [], {}, 0
        for item in items:
            if item.get("incident_id") in self._index:
                raise ValueError(f"Duplicate incident_id: {item['incident_id']}")
            prepared = self._prepare(item)
            self._index[prepared["incident_id"]] = len(self._heap)
            self._heap.append(prepared)
        for i in range(len(self._heap) // 2 - 1, -1, -1):
            self._sift_down(i)

    def update_priority(self, incident_id: str, new_score: float) -> bool:
        """Change one item's score and restore the invariant. O(log n)."""
        if incident_id not in self._index:
            return False
        i = self._index[incident_id]
        old = self._heap[i]["priority_score"]
        self._heap[i]["priority_score"] = float(new_score)
        if new_score > old:
            self._sift_up(i)
        else:
            self._sift_down(i)
        return True

    def remove(self, incident_id: str) -> bool:
        if incident_id not in self._index:
            return False
        self.update_priority(incident_id, float("inf"))
        self.extract_max()
        return True

    def contains(self, incident_id: str) -> bool:
        return incident_id in self._index

    def is_valid(self) -> bool:
        """Check heap invariant + index consistency (used by tests and the UI)."""
        for i in range(len(self._heap)):
            for c in (2 * i + 1, 2 * i + 2):
                if c < len(self._heap) and self._key(c) > self._key(i):
                    return False
            if self._index.get(self._heap[i]["incident_id"]) != i:
                return False
        return len(self._index) == len(self._heap)

    def top_k(self, k: int) -> List[Dict[str, Any]]:
        """Top-k without mutating the heap: O(k log k) using an auxiliary candidate heap."""
        if k <= 0 or not self._heap:
            return []
        out = []
        frontier = MaxHeap()
        frontier.insert({"incident_id": "0", "priority_score": self._heap[0]["priority_score"],
                         "pos": 0, "tiebreak": -self._heap[0]["_seq"]})
        while frontier and len(out) < k:
            node = frontier.extract_max()
            i = node["pos"]
            out.append(self._public(self._heap[i]))
            for c in (2 * i + 1, 2 * i + 2):
                if c < len(self._heap):
                    frontier.insert({"incident_id": str(c),
                                     "priority_score": self._heap[c]["priority_score"], "pos": c})
        return out

    def display_heap(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Array view: index, parent/children indices, id, score (for UI tables/trees)."""
        rows = []
        n = len(self._heap) if limit is None else min(limit, len(self._heap))
        for i in range(n):
            item = self._heap[i]
            rows.append({
                "index": i,
                "parent": (i - 1) // 2 if i > 0 else None,
                "left": 2 * i + 1 if 2 * i + 1 < len(self._heap) else None,
                "right": 2 * i + 2 if 2 * i + 2 < len(self._heap) else None,
                "incident_id": item["incident_id"],
                "priority_score": round(item["priority_score"], 2),
                "label": item.get("label", item.get("station_name", "")),
            })
        return rows

    def to_dot(self, max_nodes: int = 31) -> str:
        """Graphviz DOT for a binary-tree picture of the first ``max_nodes`` array slots."""
        n = min(max_nodes, len(self._heap))
        lines = ["digraph Heap {", 'node [shape=box, style="rounded,filled", fillcolor="#0D9488", '
                 'fontcolor="white", fontname="Helvetica", fontsize=10];', "edge [color=\"#64748B\"];"]
        for i in range(n):
            item = self._heap[i]
            name = str(item.get("station_name", ""))[:18].replace('"', "'")
            lines.append(f'n{i} [label="[{i}] {item["incident_id"]}\\n{name}\\nscore {item["priority_score"]:.1f}"];')
            if i > 0:
                lines.append(f"n{(i - 1) // 2} -> n{i};")
        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def _public(item: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in item.items() if k != "_seq"}

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
