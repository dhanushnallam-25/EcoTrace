"""
End-to-end smoke test on the REAL files in files/ (not part of pytest, which uses synthetic data).

    python smoke_test.py

Checks: ingestion + cleaning facts, graph construction, BFS/DFS, anomaly detection,
MaxHeap ranking, investigation narrative, report generation and that app.py imports.
Exits non-zero on the first failed check.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.bfs import bfs_downstream  # noqa: E402
from backend.data_ingestion import discover_default_files  # noqa: E402
from backend.dfs import dfs_upstream  # noqa: E402
from backend.investigation_engine import investigate  # noqa: E402
from backend.pipeline import export_processed, run_pipeline  # noqa: E402
from backend.report_generator import markdown_report  # noqa: E402

failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failures
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures += 1


def main() -> int:
    files = discover_default_files()
    print("Files:", {k: (v.name if v else None) for k, v in files.items()})
    t0 = time.perf_counter()
    s = run_pipeline(files)
    print(f"Pipeline: {time.perf_counter() - t0:.2f}s  {s.timings}")
    a = s.cleaning.audit
    q = s.cleaning.quarantine

    check("records merged without Cartesian blow-up", a["merged_records"] == 3019, str(a["merged_records"]))
    check("269 stations", a["stations"] == 269, str(a["stations"]))
    check("3,004 unique (station, timestamp) keys", a["unique_station_timestamp_keys"] == 3004)
    check("15 same-station/time multi-coordinate pairs kept", a["same_station_timestamp_different_coordinates"] == 15)
    check("date range computed dynamically", f"{a['date_min']:%Y-%m-%d}" == "2021-01-01" and f"{a['date_max']:%Y-%m-%d}" == "2021-12-31",
          f"{a['date_min']} → {a['date_max']}")
    sl = q[q["slno"] == 2300]
    check("SlNo 2300 malformed DO/Ammonia + impossible pH quarantined",
          set(sl["raw_value"]) == {"3.16.2", "0.41.83", "78.2"}, str(sl[["parameter", "raw_value"]].values.tolist()))
    row = s.records[s.records["slno_chemical"] == 2300].iloc[0]
    check("SlNo 2300 values are NaN, not 0", row[["ph", "do", "ammonia_n"]].isna().all())
    check("6 core active parameters", set(a["active_params"]) ==
          {"ph", "bod", "do", "total_coliform", "ammonia_n", "fecal_coliform"}, str(a["active_params"]))
    check("COD / heavy metals not active", "cod" in a["unmeasured_params"] and "cadmium" in a["unmeasured_params"])

    g = s.graph
    lakes = s.stations[s.stations["station_type"] == "lake"]["station_id"]
    check("graph has 269 vertices", g.get_vertex_count() == 269)
    check("graph has edges from HydroRIVERS topology", g.get_edge_count() > 0, f"E={g.get_edge_count()}, matched={s.matched_count}")
    check("all lakes isolated (in=out=0)", all(g.is_isolated(x) for x in lakes), f"{len(lakes)} lakes")
    check("every edge joins two snapped stations", all(g.vertices[u]["match_status"] == "matched" and
                                                       g.vertices[v]["match_status"] == "matched" for u, v in g.edges()))
    check("each vertex has <= 1 downstream edge (river in-tree)", all(g.out_degree(v) <= 1 for v in g.vertices))
    check("edges point downstream (non-negative river-km)", all(e["river_km"] >= -0.01 for e in s.edges))

    src = max(g.vertices, key=lambda v: len(dfs_upstream(g, v)["candidates"]))
    up = dfs_upstream(g, src)
    leaf = up["branch_paths"][0][-1] if up["branch_paths"] else src
    down = bfs_downstream(g, leaf)
    check("DFS upstream finds candidates", up["candidate_count"] > 0,
          f"{g.vertices[src]['station_name']}: {up['candidate_count']} candidates, {up['branch_count']} branches")
    check("BFS from a headwater reaches the DFS source", src in down["visited_order"],
          f"{down['affected_count']} downstream, max level {down['max_level']}")

    check("anomalies detected", int(s.obs["anomaly"].sum()) > 0, f"{int(s.obs['anomaly'].sum())} anomalous readings")
    heap = s.build_heap()
    check("MaxHeap invariant holds", heap.is_valid(), f"{len(heap)} incidents")
    order = [heap.extract_max()["priority_score"] for _ in range(len(heap))]
    check("extract_max yields non-increasing scores", all(x >= y for x, y in zip(order, order[1:])))
    top = sorted(s.incidents, key=lambda i: -i["priority_score"])[0]
    check("incident carries source SlNo + component breakdown", top["source_slno"] is not None and
          len(top["component_breakdown"]) == 5, f"{top['incident_id']} {top['station_name']} {top['priority_score']}")

    river_inc = next(i for i in sorted(s.incidents, key=lambda i: -i["priority_score"]) if i["station_type"] == "river")
    inv = investigate(river_inc, g, s.obs, s.records)
    check("investigation narrative generated", len(inv["narrative"]) >= 3)
    md = markdown_report(s, investigations=[inv])
    check("markdown report generated", md.startswith("# EcoTrace") and river_inc["incident_id"] in md)
    paths = export_processed(s)
    check("processed outputs written", all(p.exists() for p in paths.values()), str(sorted(p.name for p in paths.values())))

    for mod in ["frontend.dashboard", "frontend.dataset_page", "frontend.river_explorer", "frontend.pollution_analysis",
                "frontend.incident_priority", "frontend.investigation", "frontend.response_planner", "frontend.reports"]:
        importlib.import_module(mod)
    check("all frontend modules import", True)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
