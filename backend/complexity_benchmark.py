"""
Live DSA benchmark lab (``time.perf_counter`` + ``tracemalloc``).

Experiments (all on reproducible synthetic graphs/incidents — seeded RNG — so they are
clearly separate from the real CPCB data):

1. Adjacency list vs adjacency matrix — memory to build, neighbour-lookup time and BFS
   time, with an equivalence check that both BFS variants reach the same vertex set.
2. MaxHeap vs full sort for top-k prioritisation — heapify O(n) + k·extract O(log n)
   versus sorted() O(n log n); also "insert one new incident then read the max".
3. BFS / DFS scaling — time vs V + E to show linear growth.

Numbers are measured at run time and never hard-coded.
"""
from __future__ import annotations

import random
import statistics
import time
import tracemalloc
from typing import Callable, List

import pandas as pd

from backend.bfs import bfs_downstream, bfs_on_matrix
from backend.dfs import dfs_upstream
from backend.max_heap import MaxHeap
from backend.river_graph import DirectedRiverGraph


def synthetic_river_forest(n: int, seed: int = 42, extra_edge_ratio: float = 0.0) -> DirectedRiverGraph:
    """Random in-tree (river-like): vertex i>0 drains into a random earlier vertex.

    Vertex 0 is the outlet. Optional extra edges create a DAG for stress tests.
    """
    rng = random.Random(seed)
    g = DirectedRiverGraph()
    for i in range(n):
        g.add_vertex(f"S{i}", station_name=f"synthetic-{i}")
    for i in range(1, n):
        g.add_edge(f"S{i}", f"S{rng.randrange(0, i)}")
    for _ in range(int(n * extra_edge_ratio)):
        a, b = sorted(rng.sample(range(n), 2))
        g.add_edge(f"S{b}", f"S{a}")
    return g


def _transpose(g: DirectedRiverGraph) -> DirectedRiverGraph:
    rev = DirectedRiverGraph()
    for v in g.vertices:
        rev.add_vertex(v)
    for u, v in g.edges():
        rev.add_edge(v, u)
    return rev


def _time(fn: Callable, reps: int) -> float:
    vals = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        vals.append(time.perf_counter() - t0)
    return statistics.mean(vals)


def _peak_bytes(builder: Callable):
    tracemalloc.start()
    obj = builder()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return obj, peak


def bench_list_vs_matrix(sizes: List[int], reps: int = 3, seed: int = 42) -> pd.DataFrame:
    rows = []
    for n in sizes:
        g = synthetic_river_forest(n, seed, extra_edge_ratio=0.5)
        # Memory: measure only the adjacency structure itself (not vertex metadata).
        _, list_bytes = _peak_bytes(lambda: {u: list(vs) for u, vs in g.forward_adj.items()})
        (order, matrix), mat_bytes = _peak_bytes(g.to_adjacency_matrix)
        # BFS from the outlet over the *transposed* graph reaches every vertex,
        # so both representations do a full, comparable traversal.
        src = "S0"
        rev = _transpose(g)
        _, rev_matrix = rev.to_adjacency_matrix()
        list_reach = set(bfs_downstream(rev, src)["visited_order"])
        mat_reach = set(bfs_on_matrix(order, rev_matrix, src))
        idx = {s: i for i, s in enumerate(order)}
        probe = [f"S{i}" for i in random.Random(seed).sample(range(n), min(200, n))]
        t_list_nb = _time(lambda: [g.forward_adj[p] for p in probe], reps) / len(probe)
        t_mat_nb = _time(lambda: [[j for j, x in enumerate(matrix[idx[p]]) if x] for p in probe], reps) / len(probe)
        rows.append({
            "V": n, "E": g.get_edge_count(),
            "list_memory_KB": round(list_bytes / 1024, 1), "matrix_memory_KB": round(mat_bytes / 1024, 1),
            "list_neighbor_us": round(t_list_nb * 1e6, 3), "matrix_neighbor_us": round(t_mat_nb * 1e6, 3),
            "list_bfs_ms": round(_time(lambda: bfs_downstream(rev, src), reps) * 1e3, 3),
            "matrix_bfs_ms": round(_time(lambda: bfs_on_matrix(order, rev_matrix, src), reps) * 1e3, 3),
            "same_reachable_set": list_reach == mat_reach, "reachable": len(list_reach),
        })
        del matrix, rev_matrix
    return pd.DataFrame(rows)


def _synthetic_incidents(n: int, seed: int = 7) -> List[dict]:
    rng = random.Random(seed)
    return [{"incident_id": f"T{i}", "priority_score": round(rng.uniform(0, 100), 3)} for i in range(n)]


def bench_heap_vs_sort(sizes: List[int], k: int = 10, reps: int = 3) -> pd.DataFrame:
    rows = []
    for n in sizes:
        items = _synthetic_incidents(n)

        def heap_topk():
            h = MaxHeap(items)
            return [h.extract_max()["priority_score"] for _ in range(min(k, n))]

        def sort_topk():
            return [x["priority_score"] for x in sorted(items, key=lambda x: -x["priority_score"])[:k]]

        heap = MaxHeap(items)
        new = {"incident_id": "NEW", "priority_score": 50.0}

        def heap_insert_peek():
            heap.insert(new)
            heap.peek()
            heap.remove("NEW")

        def sort_insert_peek():
            sorted(items + [new], key=lambda x: -x["priority_score"])[0]

        rows.append({
            "I": n, "k": k,
            "heap_topk_ms": round(_time(heap_topk, reps) * 1e3, 3),
            "sort_topk_ms": round(_time(sort_topk, reps) * 1e3, 3),
            "heap_insert+peek_us": round(_time(heap_insert_peek, reps) * 1e6, 2),
            "resort_insert+peek_us": round(_time(sort_insert_peek, reps) * 1e6, 2),
            "same_topk": heap_topk() == sort_topk(),
            "heap_valid": MaxHeap(items).is_valid(),
        })
    return pd.DataFrame(rows)


def bench_traversal_scaling(sizes: List[int], reps: int = 3) -> pd.DataFrame:
    rows = []
    for n in sizes:
        g = synthetic_river_forest(n, seed=11, extra_edge_ratio=0.3)
        rev = _transpose(g)
        # DFS upstream from the outlet on g reaches everything; BFS downstream on the transpose too.
        t_dfs = _time(lambda: dfs_upstream(g, "S0"), reps)
        t_bfs = _time(lambda: bfs_downstream(rev, "S0"), reps)
        ve = n + g.get_edge_count()
        rows.append({"V": n, "E": g.get_edge_count(), "V+E": ve,
                     "bfs_ms": round(t_bfs * 1e3, 3), "dfs_ms": round(t_dfs * 1e3, 3),
                     "bfs_ns_per_(V+E)": round(t_bfs * 1e9 / ve, 1), "dfs_ns_per_(V+E)": round(t_dfs * 1e9 / ve, 1)})
    return pd.DataFrame(rows)


if __name__ == "__main__":   # python -m backend.complexity_benchmark  -> prints + saves CSVs
    from utils.config import PROCESSED_DIR
    results = {
        "benchmark_list_vs_matrix.csv": bench_list_vs_matrix([100, 500, 1000, 2000]),
        "benchmark_heap_vs_sort.csv": bench_heap_vs_sort([1000, 10000, 100000]),
        "benchmark_traversal_scaling.csv": bench_traversal_scaling([1000, 10000, 50000, 100000]),
    }
    for name, df in results.items():
        df.to_csv(PROCESSED_DIR / name, index=False)
        print(f"\n== {name} ==")
        print(df.to_string(index=False))
