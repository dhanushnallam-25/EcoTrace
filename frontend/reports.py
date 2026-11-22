"""Report generation + live DSA complexity & benchmark lab."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.complexity_benchmark import bench_heap_vs_sort, bench_list_vs_matrix, bench_traversal_scaling
from backend.investigation_engine import investigate
from backend.report_generator import html_report, incidents_csv, incidents_dataframe, markdown_report
from backend.response_planner import ResponseLog
from frontend.common import incident_lookup, incident_option_label, incidents, require_state
from frontend.styles import SERIES, data_label, hero, note, plotly_layout, section


def render() -> None:
    state = require_state()
    hero("Reports & Complexity Lab", "Downloadable investigation reports and live DSA benchmarks",
         data_label("Derived") + data_label("Synthetic"))
    t1, t2, t3 = st.tabs(["Investigation report", "DSA benchmark lab", "Existing approaches vs EcoTrace"])
    with t1:
        _reports(state)
    with t2:
        _bench()
    with t3:
        _comparison()


def _reports(state) -> None:
    log = ResponseLog()
    incs = incidents(state)
    lookup = incident_lookup(state)
    c1, c2 = st.columns(2)
    band = c1.multiselect("Bands in CSV export", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    top_n = c2.slider("Top incidents listed in report", 5, 50, 15)
    sel = [i for i in incs if i["priority_band"] in band]
    ranked = sorted(incs, key=lambda i: -i["priority_score"])
    chosen = st.multiselect("Incidents to include as full investigations (DFS + BFS narrative)",
                            [i["incident_id"] for i in ranked[:400]],
                            default=[x for x in st.session_state.get("report_incidents", []) if x in lookup]
                            or [i["incident_id"] for i in ranked if i["station_type"] == "river"][:2],
                            format_func=lambda x: incident_option_label(lookup[x]))
    invs = [investigate(lookup[i], state.graph, state.obs, state.records) for i in chosen]
    md = markdown_report(state, top_n=top_n, investigations=invs, log=log)
    d1, d2, d3 = st.columns(3)
    d1.download_button(f"Incidents CSV ({len(sel)})", incidents_csv(sel, log), "ecotrace_incidents.csv", "text/csv",
                       type="primary", width="stretch")
    d2.download_button("Report (Markdown)", md.encode("utf-8"), "ecotrace_report.md", "text/markdown", width="stretch")
    d3.download_button("Report (printable HTML → PDF)", html_report(md).encode("utf-8"), "ecotrace_report.html",
                       "text/html", width="stretch")
    note("The HTML report is print-ready: open it and use the browser's <b>Print → Save as PDF</b>. "
         "All figures are generated from the current pipeline state.")
    with st.expander("Preview report", expanded=True):
        st.markdown(md)
    with st.expander("Preview CSV"):
        st.dataframe(incidents_dataframe(sel[:500], log), hide_index=True, width="stretch")


def _bench() -> None:
    note("Benchmarks run <b>live</b> on reproducible <b>synthetic</b> river-like graphs and incident sets "
         "(seeded RNG) using <span class='et-mono'>time.perf_counter()</span> and "
         "<span class='et-mono'>tracemalloc</span>. Absolute times depend on this machine; the growth trend is the point.")
    c1, c2, c3, c4 = st.columns(4)
    g_sizes = c1.multiselect("Graph sizes (list vs matrix)", [100, 250, 500, 1000, 2000, 3000],
                             default=[100, 500, 1000, 2000])
    h_sizes = c2.multiselect("Incident counts (heap vs sort)", [1_000, 10_000, 50_000, 100_000, 200_000],
                             default=[1_000, 10_000, 100_000])
    t_sizes = c3.multiselect("Traversal sizes (BFS/DFS)", [1_000, 10_000, 50_000, 100_000, 200_000],
                             default=[1_000, 10_000, 50_000, 100_000])
    reps = c4.number_input("Repetitions", 1, 10, 3)
    if st.button("Run benchmarks", type="primary"):
        with st.spinner("Measuring…"):
            st.session_state["bench"] = (bench_list_vs_matrix(sorted(g_sizes), reps=reps),
                                         bench_heap_vs_sort(sorted(h_sizes), reps=reps),
                                         bench_traversal_scaling(sorted(t_sizes), reps=reps))
    res = st.session_state.get("bench")
    if not res:
        st.info("Click **Run benchmarks** to measure.")
    else:
        lm, hs, tr = res
        section("1 · Adjacency list vs adjacency matrix")
        a, b = st.columns(2)
        a.plotly_chart(_two_series(lm, "V", "list_memory_KB", "matrix_memory_KB", "adjacency list", "adjacency matrix",
                                   "Memory to store adjacency (KB, log)", log_y=True), width="stretch")
        b.plotly_chart(_two_series(lm, "V", "list_bfs_ms", "matrix_bfs_ms", "BFS on list", "BFS on matrix",
                                   "Full BFS time (ms, log)", log_y=True), width="stretch")
        st.dataframe(lm, hide_index=True, width="stretch")
        st.caption("Expected: list memory O(V + E), matrix O(V²); BFS O(V + E) vs O(V²). "
                   "`same_reachable_set` verifies both BFS variants agree.")
        section("2 · MaxHeap vs full sort")
        a, b = st.columns(2)
        a.plotly_chart(_two_series(hs, "I", "heap_topk_ms", "sort_topk_ms", "heapify + k·extract", "sorted() + slice",
                                   "Top-10 time (ms)"), width="stretch")
        b.plotly_chart(_two_series(hs, "I", "heap_insert+peek_us", "resort_insert+peek_us", "heap insert + peek",
                                   "append + re-sort", "Insert one incident then read max (µs, log)", log_y=True),
                       width="stretch")
        st.dataframe(hs, hide_index=True, width="stretch")
        st.caption("Top-k: heapify O(n) + k·O(log n) vs O(n log n). Python's sorted() is C-optimised Timsort, so on "
                   "small n it can beat a pure-Python heap for one-shot top-k — the heap wins decisively on the "
                   "incremental case (insert O(log n) + peek O(1) vs re-sorting O(n log n)). Read the measured numbers.")
        section("3 · BFS / DFS scaling")
        fig = go.Figure()
        for k, (col, name) in enumerate((("bfs_ms", "BFS (downstream)"), ("dfs_ms", "DFS (upstream)"))):
            fig.add_scatter(x=tr["V+E"], y=tr[col], mode="lines+markers", name=name, line=dict(color=SERIES[k], width=2),
                            marker=dict(size=8, line=dict(color="#112240", width=2)))
        fig.update_xaxes(title="V + E")
        fig.update_yaxes(title="ms")
        st.plotly_chart(plotly_layout(fig, "Traversal time vs graph size (expected linear)"), width="stretch")
        st.dataframe(tr, hide_index=True, width="stretch")
        st.caption("A roughly constant ns per (V + E) column confirms linear O(V + E) growth.")

    section("Theoretical complexity summary")
    st.dataframe(pd.DataFrame([
        ["DirectedRiverGraph.add_vertex / add_edge", "O(1) avg", "dict + set membership", "O(V + E) total"],
        ["get_downstream / get_upstream_neighbors", "O(deg)", "both adjacency directions stored", "—"],
        ["BFS downstream (deque)", "O(V + E)", "visited set, popleft O(1)", "O(V)"],
        ["DFS upstream (explicit stack)", "O(V + E)", "no recursion limit", "O(V)"],
        ["NEXT_DOWN walk (edge derivation)", "O(path length) per station", "hash-map lookups", "O(R) map"],
        ["MaxHeap insert / extract_max / update", "O(log I)", "sift up / sift down", "O(I)"],
        ["MaxHeap peek", "O(1)", "root of array", "—"],
        ["MaxHeap heapify (Floyd)", "O(I)", "bottom-up sift-down", "O(I)"],
        ["Full sort alternative", "O(I log I)", "every re-prioritisation", "O(I)"],
        ["Adjacency matrix alternative", "O(V²) memory, O(V) neighbour scan", "dense; rivers are sparse", "O(V²)"],
        ["Anomaly stats (groupby median/MAD/IQR)", "O(N log N)", "N = measurements", "O(N)"],
    ], columns=["Operation", "Time", "Notes", "Space"]), hide_index=True, width="stretch")


def _two_series(df, x, a, b, na, nb, title, log_y=False) -> go.Figure:
    fig = go.Figure()
    for k, (col, name) in enumerate(((a, na), (b, nb))):
        fig.add_scatter(x=df[x], y=df[col], mode="lines+markers", name=name, line=dict(color=SERIES[k], width=2),
                        marker=dict(size=8, line=dict(color="#112240", width=2)),
                        hovertemplate=f"{x}=%{{x}}<br>{name}: %{{y}}<extra></extra>")
    fig.update_xaxes(title=x)
    if log_y:
        fig.update_yaxes(type="log")
    return plotly_layout(fig, title, height=300)


def _comparison() -> None:
    st.dataframe(pd.DataFrame([
        ["Data handling", "Manual spreadsheet review of CPCB tables", "Automated schema mapping, quarantine of malformed "
         "& impossible values with SlNo, deterministic dedup, one-to-one merge"],
        ["River connectivity", "Station lists without topology (River/Basin columns blank)",
         "HydroRIVERS NEXT_DOWN topology → directed station graph; lakes isolated, no proximity-only edges"],
        ["Upstream tracing", "Expert knowledge / map inspection", "DFS over reverse adjacency with branch paths + "
         "contemporaneous upstream comparison"],
        ["Downstream impact", "Not quantified", "BFS hop levels + river-km to every downstream monitored point"],
        ["Prioritisation", "Ad-hoc / single-parameter exceedance lists", "Explainable 5-component score, custom MaxHeap "
         "with O(log n) updates and live re-weighting"],
        ["Anomaly detection", "Fixed limits only", "Limits + direction-aware modified z / IQR against each station's history"],
        ["Traceability", "Hard to link a flag back to raw rows", "Every incident carries source SlNo and raw values"],
        ["Response tracking", "Email / paper", "Status workflow with persisted field notes"],
        ["Limitations", "—", "Screening only; monthly samples; snapping uncertainty; no road routing"],
    ], columns=["Aspect", "Typical existing approach", "EcoTrace"]), hide_index=True, width="stretch")
