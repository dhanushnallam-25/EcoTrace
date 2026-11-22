"""Pollution Investigation: one incident → DFS upstream, BFS downstream, history, narrative."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from backend.investigation_engine import investigate
from frontend.common import (BFS_COLOR, DFS_COLOR, SOURCE_COLOR, add_edges, add_station_markers, base_map,
                             incident_lookup, incident_option_label, incidents, require_state)
from frontend.styles import (SERIES, STATUS, band_badge, data_label, hero, kpi, kpi_row, legend, note,
                             plotly_layout, section)
from utils.constants import LOG_SCALE_PARAMETERS


def render() -> None:
    state = require_state()
    incs = sorted(incidents(state), key=lambda i: -i["priority_score"])
    lookup = incident_lookup(state)
    hero("Pollution Investigation", "Trace upstream candidates (DFS) and downstream impact (BFS) for one incident",
         data_label("Government data") + data_label("Derived"))

    f1, f2 = st.columns([1, 3])
    scope = f1.radio("Show", ["River stations", "All incidents"], horizontal=False)
    pool = [i for i in incs if i["station_type"] == "river"] if scope == "River stations" else incs
    pre = st.session_state.get("inv_incident")
    ids = [i["incident_id"] for i in pool]
    idx = ids.index(pre) if pre in ids else 0
    iid = f2.selectbox("Incident (ranked by priority)", ids, index=idx,
                       format_func=lambda x: incident_option_label(lookup[x]))
    st.session_state["inv_incident"] = iid
    inc = lookup[iid]
    inv = investigate(inc, state.graph, state.obs, state.records)

    st.markdown(band_badge(inc["priority_band"]) + f" <b>{inc['incident_id']}</b> · {inc['flag_type']}",
                unsafe_allow_html=True)
    refs = ", ".join(f"{t} SlNo {n}" for t, n in inc["slno_refs"].items() if n is not None)
    kpi_row([
        kpi("Flagged value", f"{inc['value']:g} {inc['unit']}", f"{inc['parameter_label']} · {inc['date']}", accent=True),
        kpi("Criterion", inc["threshold_text"] or "—", (inc["threshold_basis"] or "")[:40]),
        kpi("Priority score", f"{inc['priority_score']:.1f}", f"{inc['priority_band']} priority"),
        kpi("Upstream candidates (DFS)", inv["dfs"]["candidate_count"], f"{inv['dfs']['branch_count']} branch path(s)"),
        kpi("Downstream stations (BFS)", inv["bfs"]["affected_count"], f"max {inv['bfs']['max_level']} hops"),
        kpi("Source rows", inc["source_slno"], refs[:40]),
    ])

    section("Investigation narrative (auto-generated from the data)")
    st.markdown("<div class='et-card'>" + "".join(f"<p>{_md_bold(p)}</p>" for p in inv["narrative"]) + "</div>",
                unsafe_allow_html=True)

    left, right = st.columns([1.2, 1])
    with left:
        section("Station time series")
        st.plotly_chart(_history_chart(inv, inc), width="stretch", config={"displayModeBar": False})
        section("Upstream parameter comparison (nearest reading within ±45 days)")
        if inv["upstream_table"].empty:
            st.info("No upstream monitored stations in the graph.")
        else:
            st.dataframe(inv["upstream_table"], hide_index=True, width="stretch")
        section("Downstream impact")
        if inv["downstream_table"].empty:
            st.info("No downstream monitored stations in the graph.")
        else:
            st.dataframe(inv["downstream_table"], hide_index=True, width="stretch")
    with right:
        section("Investigation subgraph")
        g = state.graph
        sid = inc["station_id"]
        sub = {sid} | set(inv["dfs"]["candidates"]) | set(inv["bfs"]["affected"])
        v = g.vertices[sid]
        m = base_map(state, center=[v["lat"], v["lon"]] if v.get("lat") else None, zoom=9 if len(sub) > 1 else 11)
        hl = {sid: SOURCE_COLOR}
        labels = {sid: "Incident station"}
        for s in inv["dfs"]["candidates"]:
            hl[s], labels[s] = DFS_COLOR, f"Upstream candidate (depth {inv['dfs']['depth'][s]})"
        for s in inv["bfs"]["affected"]:
            hl[s], labels[s] = BFS_COLOR, f"Downstream (hop {inv['bfs']['levels'][s]})"
        up_edges = {(c, p) for c, p in inv["dfs"]["parent"].items() if p is not None}
        dn_edges = set(inv["bfs"]["traversal_edges"])
        add_edges(m, state, [e for e in state.edges if (e["from"], e["to"]) in up_edges], color=DFS_COLOR,
                  weight=3.5, animate=True, name="Upstream (DFS) edges")
        add_edges(m, state, [e for e in state.edges if (e["from"], e["to"]) in dn_edges], color=BFS_COLOR,
                  weight=3.5, animate=True, name="Downstream (BFS) edges")
        add_station_markers(m, state, highlight=hl, labels=labels, only=sub)
        st_folium(m, height=470, use_container_width=True, returned_objects=[], key=f"inv_map_{iid}")
        legend([(SOURCE_COLOR, "Incident station"), (DFS_COLOR, "Upstream candidate (DFS)"),
                (BFS_COLOR, "Downstream impact (BFS)")])
        if inv["dfs"]["branch_paths"]:
            section("DFS branch paths (walking upstream)")
            for path in inv["dfs"]["branch_paths"]:
                st.markdown("• " + " ← ".join(f"{g.vertices[p]['station_name'][:28]}" for p in path))
        c1, c2 = st.columns(2)
        if c1.button("Add to report", width="stretch"):
            lst = st.session_state.setdefault("report_incidents", [])
            if iid not in lst:
                lst.append(iid)
            st.success(f"{iid} added ({len(lst)} in report).")
        if c2.button("Open in Response Planner", width="stretch"):
            st.session_state["rp_incident"] = iid
            st.session_state["nav_pending"] = "Response Planner"
            st.rerun()

    section("Scientific limitations")
    note("<br>".join(f"• {lim}" for lim in inv["limitations"]), warn=True)


def _md_bold(text: str) -> str:
    import html
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


def _history_chart(inv, inc) -> go.Figure:
    h = inv["history"]
    fig = go.Figure()
    if len(h):
        colors = [STATUS["High"] if v else SERIES[0] for v in h["violated"]]
        fig.add_scatter(x=h["timestamp"], y=h["value"], mode="lines+markers", name=inc["station_name"][:30],
                        line=dict(color=SERIES[0], width=2),
                        marker=dict(size=9, color=colors, line=dict(color="#112240", width=2)),
                        customdata=h["source_slno"].astype(str),
                        hovertemplate="%{x|%Y-%m-%d}: %{y}<br>SlNo %{customdata}<extra></extra>")
        fig.add_scatter(x=[inc["timestamp"]], y=[inc["value"]], mode="markers", name="this incident",
                        marker=dict(symbol="star", size=18, color="#F1F5F9", line=dict(color=STATUS["High"], width=2)),
                        hoverinfo="skip")
    spec = inc.get("threshold") or {}
    for key in ("min", "max"):
        if spec.get(key) is not None:
            fig.add_hline(y=spec[key], line_dash="dash", line_color=STATUS["High"],
                          annotation_text=f"criterion {key} {spec[key]:g}", annotation_font_color="#CBD5E1")
    fig.update_yaxes(title=f"{inc['parameter_label']} ({inc['unit']})",
                     type="log" if inc["primary_parameter"] in LOG_SCALE_PARAMETERS else "linear")
    return plotly_layout(fig, f"{inc['parameter_label']} at {inc['station_name'][:40]} (red = breach)", height=320)


__all__ = ["render", "pd"]
