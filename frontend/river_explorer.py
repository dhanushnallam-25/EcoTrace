"""River Network Explorer: HydroRIVERS map, station graph and live BFS / DFS runs."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from backend.bfs import bfs_downstream
from backend.dfs import dfs_upstream
from frontend.common import (BFS_COLOR, DFS_COLOR, SOURCE_COLOR, add_edges, add_station_markers, base_map,
                             require_state, station_legend_items)
from frontend.styles import TEAL, data_label, hero, kpi, kpi_row, legend, note, section


def render() -> None:
    state = require_state()
    g = state.graph
    hero("River Network Explorer", "DirectedRiverGraph (dict adjacency lists) built from HydroRIVERS NEXT_DOWN topology",
         data_label("Derived"))
    in_deg = [g.in_degree(v) for v in g.vertices]
    kpi_row([
        kpi("Vertices (V)", g.get_vertex_count(), "all stations", accent=True),
        kpi("Edges (E)", g.get_edge_count(), "directed u → v (downstream)"),
        kpi("Connected vertices", len(g.connected_vertices()), "degree > 0"),
        kpi("Isolated vertices", g.get_vertex_count() - len(g.connected_vertices()), "lakes, unsnapped, unknown"),
        kpi("Confluence vertices", sum(1 for d in in_deg if d > 1), "in-degree > 1"),
    ])

    connected = sorted(g.connected_vertices(), key=lambda s: g.vertices[s]["station_name"])
    others = sorted(set(g.vertices) - set(connected), key=lambda s: g.vertices[s]["station_name"])
    options = connected + others
    label = {s: f"{g.vertices[s]['station_name']} ({s})" + ("" if s in connected else " — isolated") for s in options}
    c1, c2, c3 = st.columns([3, 1, 1])
    sid = c1.selectbox("Station", options, format_func=label.get, key="rx_station")
    if c2.button("Run BFS Downstream", type="primary", width="stretch"):
        t0 = time.perf_counter()
        res = bfs_downstream(g, sid)
        st.session_state["rx_result"] = ("BFS", sid, res, (time.perf_counter() - t0) * 1e3)
    if c3.button("Run DFS Upstream", type="primary", width="stretch"):
        t0 = time.perf_counter()
        res = dfs_upstream(g, sid)
        st.session_state["rx_result"] = ("DFS", sid, res, (time.perf_counter() - t0) * 1e3)

    result = st.session_state.get("rx_result")
    if result and result[1] != sid:
        result = None
    v = g.vertices[sid]
    note(f"<b>{v['station_name']}</b> · {v['match_status']} · in-degree {g.in_degree(sid)}, out-degree "
         f"{g.out_degree(sid)} · HYRIV_ID {v.get('hyriv_id') or '—'} · MAIN_RIV {v.get('main_riv') or '—'} · "
         f"distance to outlet {v['dist_dn_km']:.1f} km" if v.get("dist_dn_km") is not None else
         f"<b>{v['station_name']}</b> · {v['match_status']} — isolated vertex: BFS/DFS will return only the station itself.")

    left, right = st.columns([1.5, 1])
    with left:
        m = base_map(state, center=[v["lat"], v["lon"]] if v.get("lat") else None, zoom=8 if result else 7)
        add_edges(m, state, state.edges, color=TEAL, weight=1.6)
        highlight, labels = {sid: SOURCE_COLOR}, {}
        if result:
            kind, _, res, _ = result
            color = BFS_COLOR if kind == "BFS" else DFS_COLOR
            if kind == "BFS":
                tree = {(u, w) for u, w in res["traversal_edges"]}
                for s, lvl in res["levels"].items():
                    if s != sid:
                        highlight[s], labels[s] = color, f"BFS hop level {lvl}"
            else:
                tree = {(c, p) for c, p in res["parent"].items() if p is not None}
                for s, d in res["depth"].items():
                    if s != sid:
                        highlight[s], labels[s] = color, f"DFS upstream depth {d}"
            sel = [e for e in state.edges if (e["from"], e["to"]) in tree]
            add_edges(m, state, sel, color=color, weight=3.5, animate=True, name=f"{kind} traversal edges")
        add_station_markers(m, state, highlight=highlight, labels=labels)
        st_folium(m, height=560, use_container_width=True, returned_objects=[], key=f"rx_map_{sid}_{bool(result)}")
        legend(station_legend_items() + [(SOURCE_COLOR, "Selected station"), (BFS_COLOR, "BFS-visited (downstream)"),
                                         (DFS_COLOR, "DFS-visited (upstream)")])
    with right:
        if not result:
            section("How to use")
            st.markdown("Pick a station and run **BFS Downstream** (who is affected?) or **DFS Upstream** "
                        "(which upstream monitored points are candidates?). Results are computed live on the "
                        "adjacency lists — nothing is pre-computed or hard-coded.")
        else:
            _result_panel(state, *result)

    with st.expander("Adjacency list (display_graph) — connected vertices"):
        st.code(g.display_graph(), language=None)
    with st.expander("Directed edges with traced HydroRIVERS paths"):
        st.dataframe(pd.DataFrame([{k: (" → ".join(map(str, val)) if k == "reach_path" else val)
                                    for k, val in e.items()} for e in state.edges]), hide_index=True, width="stretch")
    with st.expander("Station ↔ reach matching table"):
        cols = ["station_id", "station_name", "station_type", "match_status", "hyriv_id", "main_riv", "ord_stra",
                "snap_distance_km", "dist_dn_km", "in_degree", "out_degree"]
        st.dataframe(state.stations[cols], hide_index=True, width="stretch")


def _result_panel(state, kind, sid, res, ms) -> None:
    g = state.graph
    if kind == "BFS":
        section(f"BFS downstream from {sid} · {ms:.3f} ms")
        st.markdown(f"**{res['affected_count']}** downstream station(s) reachable · max hop level "
                    f"**{res['max_level']}**")
        rows = [{"Order": k, "Station": s, "Name": g.vertices[s]["station_name"], "Hop level": res["levels"][s]}
                for k, s in enumerate(res["visited_order"])]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if res["traversal_edges"]:
            st.markdown("**BFS tree edges:** " + " · ".join(f"{u}→{w}" for u, w in res["traversal_edges"]))
        note("<b>Complexity.</b> Each vertex is enqueued once (visited set) and each outgoing edge in "
             "<span class='et-mono'>forward_adj</span> is scanned once → <b>O(V + E)</b> time, O(V) extra space. "
             "<span class='et-mono'>collections.deque.popleft()</span> is O(1).")
    else:
        section(f"DFS upstream from {sid} · {ms:.3f} ms")
        st.markdown(f"**{res['candidate_count']}** upstream candidate(s) across **{res['branch_count']}** branch path(s)")
        rows = [{"Order": k, "Station": s, "Name": g.vertices[s]["station_name"], "Depth": res["depth"][s]}
                for k, s in enumerate(res["traversal_order"])]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for path in res["branch_paths"]:
            st.markdown("• " + " ← ".join(f"`{p}`" for p in path))
        note("<b>Complexity.</b> Iterative DFS with an explicit stack over "
             "<span class='et-mono'>reverse_adj</span>: every vertex pushed once, every edge examined once → "
             "<b>O(V + E)</b>. Branch paths are rebuilt from parent pointers.")
        for c in res["caveats"]:
            st.caption("⚠ " + c)
