"""
EcoTrace — River Pollution Investigation & Response Planner (Streamlit entry point).

Run:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(page_title="EcoTrace", page_icon="🌊", layout="wide", initial_sidebar_state="expanded")

from backend.data_ingestion import discover_default_files  # noqa: E402
from frontend import (dashboard, dataset_page, incident_priority, investigation, pollution_analysis,  # noqa: E402
                      reports, response_planner, river_explorer)
from frontend.common import get_state, load_defaults  # noqa: E402
from frontend.styles import TEAL, inject_css  # noqa: E402

PAGES = {
    "Overview Dashboard": dashboard.render,
    "Dataset Management": dataset_page.render,
    "River Network Explorer": river_explorer.render,
    "Pollution Analysis": pollution_analysis.render,
    "Incident Prioritization": incident_priority.render,
    "Pollution Investigation": investigation.render,
    "Response Planner": response_planner.render,
    "Reports & Benchmarks": reports.render,
}


def sidebar() -> str:
    with st.sidebar:
        st.markdown(f"<h2 style='margin-bottom:0'>🌊 EcoTrace</h2><div style='color:#94A3B8;font-size:0.82rem;"
                    f"margin-bottom:12px'>River pollution investigation &amp; response</div>", unsafe_allow_html=True)
        if "nav_pending" in st.session_state:
            st.session_state["nav"] = st.session_state.pop("nav_pending")
        page = st.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
        st.divider()
        state = get_state()
        if state is None:
            st.caption("No dataset loaded")
        else:
            a = state.cleaning.audit
            st.markdown(f"<div style='font-size:0.82rem;color:#CBD5E1'><b style='color:{TEAL}'>● Dataset loaded</b><br>"
                        f"{a['merged_records']:,} records · {a['stations']} stations<br>"
                        f"Graph V={state.graph.get_vertex_count()}, E={state.graph.get_edge_count()}<br>"
                        f"{len(state.incidents):,} incidents</div>", unsafe_allow_html=True)
        if st.button("Load Default Karnataka CPCB + HydroRIVERS Dataset", width="stretch", type="primary"):
            _load_default()
        st.caption("Data: CPCB manual surface-water monitoring (Karnataka, via NWDP) · HydroRIVERS v1.0 "
                   "(Lehner & Grill 2013). Screening tool — not proof of source.")
    return page


def _load_default() -> None:
    try:
        with st.spinner("Loading default dataset (first run clips HydroRIVERS and caches it)…"):
            load_defaults()
    except Exception as err:
        st.sidebar.error(f"Could not load defaults: {err}")


def main() -> None:
    inject_css()
    # One-click demo: auto-load the bundled files on first visit when they are present.
    if get_state() is None and not st.session_state.get("_autoload_tried"):
        st.session_state["_autoload_tried"] = True
        found = discover_default_files()
        if found.get("chemical") is not None or found.get("biological") is not None:
            _load_default()
    page = sidebar()
    PAGES[page]()


main()
