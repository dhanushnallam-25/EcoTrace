"""Home / Overview dashboard — every number is read from the live pipeline state."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from frontend.common import (add_edges, add_station_markers, base_map, get_heap, incidents, require_state,
                             station_legend_items)
from frontend.styles import (STATUS, TEAL, data_label, hero, kpi, kpi_row, legend, note, plotly_layout, section)


def render() -> None:
    state = require_state()
    incs = incidents(state)
    a = state.cleaning.audit
    high = [i for i in incs if i["priority_band"] == "High"]
    hero("EcoTrace — River Pollution Investigation & Response Planner",
         "Karnataka surface-water screening built on CPCB monitoring data and HydroRIVERS topology",
         data_label("Government data") + data_label("Derived"))

    kpi_row([
        kpi("Total stations", a["stations"], f"{(state.stations['station_type'] == 'lake').sum()} lakes/tanks · "
            f"{(state.stations['station_type'] == 'river').sum()} river-type", accent=True),
        kpi("Matched river vertices", state.matched_count, f"snapped ≤ {state.config.snap_distance_km:g} km"),
        kpi("Directed edges", state.graph.get_edge_count(), "from HydroRIVERS NEXT_DOWN"),
        kpi("Total records", f"{a['merged_records']:,}", f"{a['quarantined_values']} values quarantined"),
    ])
    st.write("")
    kpi_row([
        kpi("Flagged incidents", f"{len(incs):,}", "threshold breach or anomaly", accent=True),
        kpi("High-priority incidents", len(high), f"score ≥ {state.config.high_priority_threshold:g}"),
        kpi("Affected downstream stations", state.affected_downstream_stations("High"),
            "BFS union from high-priority sources"),
        kpi("Date coverage", f"{a['date_min']:%d %b %Y}", f"to {a['date_max']:%d %b %Y}"),
    ])

    note("Scores are <b>screening signals</b> to prioritise follow-up, not proof of a pollution source. "
         "Readings are CPCB monthly grab samples; graph links are derived by snapping stations to HydroRIVERS.")

    left, right = st.columns([1.35, 1])
    with left:
        section("Station network overview")
        m = base_map(state)
        add_edges(m, state, state.edges)
        add_station_markers(m, state)
        st_folium(m, height=520, use_container_width=True, returned_objects=[], key="dash_map")
        legend(station_legend_items())
    with right:
        section("Incident priority distribution")
        st.plotly_chart(_band_chart(incs, state.config.high_priority_threshold), width="stretch",
                        config={"displayModeBar": False})
        section("Incidents by primary parameter")
        st.plotly_chart(_param_chart(incs), width="stretch", config={"displayModeBar": False})

    section("Top incidents (custom MaxHeap · non-destructive top-k)")
    heap = get_heap(state)
    top = heap.top_k(10)
    if top:
        df = pd.DataFrame([{
            "Rank": k, "Incident": i["incident_id"], "Score": i["priority_score"], "Band": i["priority_band"],
            "Station": i["station_name"], "Type": i["station_type"], "Date": i["date"],
            "Parameter": i["parameter_label"], "Value": i["value"], "Unit": i["unit"],
            "Criterion": i["threshold_text"], "Downstream stations": i["downstream_count"],
            "Source SlNo": i["source_slno"]} for k, i in enumerate(top, 1)])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100,
                                                                              format="%.1f")})
    else:
        st.info("The heap is empty (all incidents extracted). Reset it on the Incident Prioritization page.")


def _band_chart(incs, high_thr: float) -> go.Figure:
    scores = pd.Series([i["priority_score"] for i in incs], dtype=float)
    bands = pd.Series([i["priority_band"] for i in incs])
    fig = go.Figure()
    bins = dict(start=0, end=100, size=5)
    for band in ("Low", "Medium", "High"):
        sel = scores[bands == band]
        fig.add_histogram(x=sel, xbins=bins, name=f"{band} ({len(sel)})", marker_color=STATUS[band],
                          marker_line=dict(color="#112240", width=2),
                          hovertemplate="score %{x}<br>%{y} incidents<extra>" + band + "</extra>")
    fig.update_layout(barmode="stack")
    fig.add_vline(x=high_thr, line_dash="dot", line_color="#F1F5F9", opacity=0.6,
                  annotation_text=f"high ≥ {high_thr:g}", annotation_font_color="#CBD5E1")
    fig.update_xaxes(title="priority score (0–100)", range=[0, 100])
    fig.update_yaxes(title="incidents")
    return plotly_layout(fig, height=250)


def _param_chart(incs) -> go.Figure:
    c = Counter(i["parameter_label"] for i in incs)
    items = sorted(c.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(x=[v for _, v in items], y=[k for k, _ in items], orientation="h",
                           marker_color=TEAL, text=[v for _, v in items], textposition="outside",
                           textfont=dict(color="#CBD5E1"),
                           hovertemplate="%{y}: %{x} incidents<extra></extra>"))
    fig.update_xaxes(title="incidents (primary parameter)")
    return plotly_layout(fig, height=250, legend_on=False)
