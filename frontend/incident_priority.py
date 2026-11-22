"""Incident Prioritization with the custom MaxHeap: peek / extract / insert / reweight."""
from __future__ import annotations

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.incident_scoring import COMPONENT_LABELS, compute_score, explain_components, priority_band
from frontend.common import (current_weights, get_heap, incident_lookup, incident_option_label, incidents,
                             require_state, reset_heap)
from frontend.styles import SERIES, band_badge, data_label, hero, kpi, kpi_row, note, plotly_layout, section
from utils.validation import validate_weights


def render() -> None:
    state = require_state()
    heap = get_heap(state)
    incs = incidents(state)
    hero("Incident Prioritization", "Array-backed binary MaxHeap (no heapq) ordering incidents by explainable score",
         data_label("Derived"))

    kpi_row([
        kpi("Items in heap", len(heap), f"of {len(incs)} incidents", accent=True),
        kpi("Heap height", (len(heap)).bit_length(), "⌊log₂ n⌋ + 1 levels"),
        kpi("Invariant holds", "Yes" if heap.is_valid() else "NO", "parent ≥ children, index map consistent"),
        kpi("Extracted this session", len(st.session_state.get("heap_log", [])), "Extract Max operations"),
    ])

    section("Heap operations")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("Peek Max — O(1)", width="stretch"):
        t0 = time.perf_counter()
        top = heap.peek()
        st.session_state["heap_msg"] = ("peek", top, (time.perf_counter() - t0) * 1e6)
    if b2.button("Extract Max — O(log n)", type="primary", width="stretch"):
        t0 = time.perf_counter()
        top = heap.extract_max()
        dt = (time.perf_counter() - t0) * 1e6
        if top:
            st.session_state.setdefault("heap_log", []).append(top)
        st.session_state["heap_msg"] = ("extract", top, dt)
    if b3.button("Reset heap (heapify — O(n))", width="stretch"):
        t0 = time.perf_counter()
        reset_heap(state)
        st.session_state["heap_msg"] = ("reset", None, (time.perf_counter() - t0) * 1e6)
        heap = st.session_state["heap"]
    with b4.popover("Insert Test Incident", width="stretch"):
        _insert_form(state, heap)

    msg = st.session_state.get("heap_msg")
    if msg:
        op, item, us = msg
        if op == "reset":
            note(f"Heap rebuilt bottom-up with Floyd's heapify in {us:,.0f} µs.")
        elif item is None:
            note("Heap is empty.", warn=True)
        else:
            note(f"<b>{op.title()}</b> in {us:,.1f} µs → {band_badge(item['priority_band'])} "
                 f"<b>{item['incident_id']}</b> · {item['station_name']} · {item['parameter_label']} = "
                 f"{item['value']:g} {item['unit']} · score <b>{item['priority_score']:.2f}</b>")

    tabs = st.tabs(["Ranked incidents", "Heap tree", "Heap array", "Score breakdown", "Adjust scoring weights",
                    "Extraction log"])
    with tabs[0]:
        top = heap.top_k(50)
        st.dataframe(pd.DataFrame([{"Rank": k, "Incident": i["incident_id"], "Score": i["priority_score"],
                                    "Band": i["priority_band"], "Station": i["station_name"], "Date": i["date"],
                                    "Parameter": i["parameter_label"], "Value": i["value"], "Unit": i["unit"],
                                    "Flag": i["flag_type"], "Downstream": i["downstream_count"]}
                                   for k, i in enumerate(top, 1)]), hide_index=True, width="stretch", height=420,
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100,
                                                                              format="%.1f")})
        st.caption("Top 50 via non-destructive top-k: an auxiliary heap over candidate array positions, O(k log k).")
    with tabs[1]:
        n = st.slider("Nodes to draw (first array slots)", 7, 63, 31, 8)
        st.graphviz_chart(heap.to_dot(n), width="stretch")
        st.caption("Node label: [array index] incident id · station · score. Children of index i are 2i+1 and 2i+2.")
    with tabs[2]:
        st.dataframe(pd.DataFrame(heap.display_heap(limit=63)), hide_index=True, width="stretch")
    with tabs[3]:
        _breakdown(state, incs)
    with tabs[4]:
        _weights(state)
    with tabs[5]:
        log = st.session_state.get("heap_log", [])
        if log:
            st.dataframe(pd.DataFrame([{"Order": k, "Incident": i["incident_id"], "Score": i["priority_score"],
                                        "Station": i["station_name"], "Parameter": i["parameter_label"]}
                                       for k, i in enumerate(log, 1)]), hide_index=True, width="stretch")
            st.caption("Scores are non-increasing down this list — the heap property in action.")
        else:
            st.info("No Extract Max operations yet.")


def _insert_form(state, heap) -> None:
    st.caption("Creates a clearly labelled **TEST** incident (synthetic) from component values.")
    with st.form("insert_test"):
        name = st.text_input("Label", "TEST incident")
        comps = {k: st.slider(COMPONENT_LABELS[k], 0.0, 1.0, 0.5, 0.05, key=f"ins_{k}") for k in COMPONENT_LABELS}
        if st.form_submit_button("Insert — O(log n)", type="primary"):
            w = current_weights(state)
            score = compute_score(comps, w)
            iid = f"TEST-{int(time.time() * 1000) % 10_000_000}"
            item = {"incident_id": iid, "priority_score": score, "station_name": f"[SYNTHETIC] {name}",
                    "station_id": "TEST", "station_type": "test", "parameter_label": "test", "value": 0.0,
                    "unit": "", "date": "—", "flag_type": "synthetic test", "downstream_count": 0,
                    "components": comps, "component_breakdown": explain_components(comps, w),
                    "priority_band": priority_band(score, state.config.high_priority_threshold)}
            t0 = time.perf_counter()
            heap.insert(item)
            st.session_state["heap_msg"] = ("insert", item, (time.perf_counter() - t0) * 1e6)
            st.rerun()


def _breakdown(state, incs) -> None:
    lookup = incident_lookup(state)
    ranked = sorted(incs, key=lambda i: -i["priority_score"])[:300]
    iid = st.selectbox("Incident", [i["incident_id"] for i in ranked],
                       format_func=lambda x: incident_option_label(lookup[x]))
    inc = lookup[iid]
    rows = inc["component_breakdown"]
    fig = go.Figure()
    for k, r in enumerate(rows):
        fig.add_bar(y=["score"], x=[r["points"]], orientation="h", name=f"{r['component']} ({r['points']:.1f})",
                    marker_color=SERIES[k], marker_line=dict(color="#112240", width=2),
                    hovertemplate=f"{r['label']}<br>value {r['value']:.3f} × weight {r['weight']:.2f}"
                                  f"<br>= {r['points']:.2f} of {r['max_points']:.1f} pts<extra></extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[0, 100], title="points (0–100)")
    st.plotly_chart(plotly_layout(fig, f"{iid}: {inc['priority_score']:.2f} / 100", height=200), width="stretch",
                    config={"displayModeBar": False})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown(f"Score = 100 · Σ wᵢ·cᵢ / Σ wᵢ. Primary parameter **{inc['parameter_label']} = {inc['value']:g} "
                f"{inc['unit']}** (criterion {inc['threshold_text'] or 'n/a'}); violated: "
                + (", ".join(f"{v['label']} ({v['value']:g})" for v in inc["violated_parameters"]) or "none")
                + f"; {inc['downstream_count']} BFS-reachable downstream stations.")


def _weights(state) -> None:
    w = current_weights(state)
    st.caption("Changing weights re-scores every incident from its stored components (O(I)) and re-heapifies (O(I)). "
               "Detection is not re-run.")
    with st.form("weights_form"):
        cols = st.columns(5)
        new = {k: cols[n].number_input(k, 0.0, 1.0, float(w.get(k, 0.0)), 0.05, key=f"wt_{k}")
               for n, k in enumerate(COMPONENT_LABELS)}
        a, b = st.columns(2)
        apply = a.form_submit_button("Apply weights", type="primary")
        restore = b.form_submit_button("Restore defaults (0.35 / 0.20 / 0.20 / 0.15 / 0.10)")
    if apply:
        ok, msg = validate_weights(new)
        if not ok:
            st.error(msg)
            return
        st.session_state["weights"] = new
        reset_heap(state)
        st.success(msg + " Heap rebuilt.")
        st.rerun()
    if restore:
        st.session_state.pop("weights", None)
        reset_heap(state)
        st.rerun()
