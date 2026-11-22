"""Dataset Management: one-click defaults, uploads, schema mapping and data-quality audit."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.data_ingestion import discover_default_files, save_upload
from frontend.common import build_state, get_state, load_defaults
from frontend.styles import MUTED, TEAL, data_label, hero, kpi, kpi_row, note, plotly_layout, section
from utils.config import PROCESSED_DIR, PipelineConfig
from utils.validation import validate_river_archive


def render() -> None:
    hero("Dataset Management", "Load the bundled Karnataka datasets or upload your own, then audit data quality",
         data_label("Government data") + data_label("Derived"))
    defaults = discover_default_files()

    c1, c2 = st.columns([1, 1])
    with c1:
        section("Bundled default files (files/)")
        rows = [{"Role": k, "File": (p.name if p else "— not found —"),
                 "Size (MB)": round(p.stat().st_size / 1e6, 2) if p else None} for k, p in defaults.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if st.button("Load Default Karnataka CPCB + HydroRIVERS Dataset", type="primary", width="stretch",
                     disabled=defaults.get("chemical") is None and defaults.get("biological") is None):
            with st.spinner("Running pipeline on default files…"):
                load_defaults(_config_from_widgets())
            st.success("Default dataset loaded.")
    with c2:
        section("Pipeline settings")
        cfg = st.session_state.get("config") or PipelineConfig()
        st.session_state["w_snap"] = st.slider("Snap distance (km) — station → HydroRIVERS reach", 0.25, 5.0,
                                               float(cfg.snap_distance_km), 0.25)
        st.session_state["w_cov"] = st.slider("Active-parameter coverage threshold", 0.01, 0.5,
                                              float(cfg.active_param_min_coverage), 0.01,
                                              help="Parameters populated on fewer records are treated as not monitored "
                                                   "and excluded from completeness scoring.")
        st.session_state["w_lake"] = st.checkbox("Also snap lake/tank stations (not recommended)",
                                                 value=cfg.snap_lake_stations)

    section("Upload your own files")
    u1, u2, u3, u4 = st.columns(4)
    chem = u1.file_uploader("Chemical CSV", type=["csv"], key="up_chem")
    bio = u2.file_uploader("Biological CSV", type=["csv"], key="up_bio")
    phys = u3.file_uploader("Physical CSV (optional)", type=["csv"], key="up_phys")
    riv = u4.file_uploader("HydroRIVERS GDB/Shapefile ZIP", type=["zip"], key="up_riv")
    use_default_rivers = st.checkbox("Use bundled HydroRIVERS if no river ZIP is uploaded", value=True)
    if st.button("Process & Build Pipeline", type="primary"):
        sources = {"chemical": None, "biological": None, "physical": None, "hydrorivers": None}
        for kind, up in (("chemical", chem), ("biological", bio), ("physical", phys), ("hydrorivers", riv)):
            if up is not None:
                sources[kind] = save_upload(up, kind)
        if sources["chemical"] is None and sources["biological"] is None:
            if get_state() is not None:
                sources.update({k: v for k, v in st.session_state["sources"].items() if sources.get(k) is None})
            else:
                sources.update({k: v for k, v in defaults.items() if sources.get(k) is None})
        if sources["hydrorivers"] is None and use_default_rivers:
            sources["hydrorivers"] = defaults.get("hydrorivers")
        if sources["hydrorivers"] is not None:
            ok, msg = validate_river_archive(sources["hydrorivers"])
            if not ok:
                st.error(msg)
                st.stop()
        try:
            with st.spinner("Processing…"):
                build_state(sources, _config_from_widgets())
            st.success("Pipeline rebuilt from: " + ", ".join(f"{k}={v.name}" for k, v in sources.items() if v))
        except Exception as err:   # surface schema/validation problems to the user
            st.error(f"Pipeline failed: {err}")

    state = get_state()
    if state is None:
        note("No dataset loaded yet — use the button above.")
        return
    _audit(state)


def _config_from_widgets() -> PipelineConfig:
    base = st.session_state.get("config") or PipelineConfig()
    cfg = PipelineConfig(**base.to_dict())
    cfg.snap_distance_km = float(st.session_state.get("w_snap", cfg.snap_distance_km))
    cfg.active_param_min_coverage = float(st.session_state.get("w_cov", cfg.active_param_min_coverage))
    cfg.snap_lake_stations = bool(st.session_state.get("w_lake", cfg.snap_lake_stations))
    return cfg


def _audit(state) -> None:
    a = state.cleaning.audit
    section("Data-quality audit (current pipeline)")
    kpi_row([
        kpi("Merged records", f"{a['merged_records']:,}", "one row per station visit", accent=True),
        kpi("Stations", a["stations"], f"{a['unique_station_timestamp_keys']:,} unique (station, time) keys"),
        kpi("Duplicates removed", a["duplicates_removed"], "exact (station, time, lat, lon)"),
        kpi("Same station+time, other coords", a["same_station_timestamp_different_coordinates"],
            "kept as separate sampling points"),
        kpi("Quarantined values", a["quarantined_values"], "malformed / physically impossible"),
        kpi("Date range", f"{a['date_min']:%Y-%m-%d}", f"to {a['date_max']:%Y-%m-%d}"),
    ])
    timings = " · ".join(f"{k} {v:.2f}s" for k, v in state.timings.items())
    river_note = (f"HydroRIVERS: {len(state.rivers):,} reaches clipped to Karnataka bbox; "
                  f"{'loaded from cache' if state.river_cache_hit else 'clipped from source and cached'} "
                  f"(<span class='et-mono'>{state.river_cache.name if state.river_cache else '-'}</span>)."
                  if state.rivers is not None else "No river network loaded — every station is an isolated vertex.")
    note(f"{river_note}<br>Stage timings: {timings}. Processed tables + provenance.json written to "
         f"<span class='et-mono'>data/processed/</span>.")

    tabs = st.tabs(["Parameter coverage", "Schema mapping", "Quarantine", "Duplicates & multi-coordinate",
                    "Per-table counts", "Station registry"])
    cat = state.cleaning.param_catalog
    with tabs[0]:
        rows = sorted(cat.values(), key=lambda e: -e["coverage"])
        fig = go.Figure(go.Bar(
            x=[round(e["coverage"] * 100, 1) for e in rows], y=[e["label"] for e in rows], orientation="h",
            marker_color=[TEAL if e["active"] else MUTED for e in rows],
            text=[f"{e['coverage'] * 100:.1f}% {'active' if e['active'] else 'not monitored'}" for e in rows],
            textposition="outside", textfont=dict(color="#CBD5E1", size=10),
            hovertemplate="%{y}: %{x}% of records<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(title="% of merged records with a value", range=[0, 125])
        fig.add_vline(x=state.config.active_param_min_coverage * 100, line_dash="dot", line_color="#F1F5F9",
                      annotation_text="active threshold", annotation_font_color="#CBD5E1")
        st.plotly_chart(plotly_layout(fig, height=max(320, 18 * len(rows)), legend_on=False), width="stretch",
                        config={"displayModeBar": False})
        st.caption(f"Active (scored) parameters: {', '.join(cat[p]['label'] for p in state.cleaning.active_params)}. "
                   "Completeness is measured only against these — stations are never penalised for heavy metals "
                   "or COD that are not part of the monitoring suite.")
    with tabs[1]:
        st.dataframe(state.cleaning.schema_report, hide_index=True, width="stretch")
    with tabs[2]:
        q = state.cleaning.quarantine
        if q.empty:
            st.success("No values quarantined.")
        else:
            st.dataframe(q.assign(timestamp=q["timestamp"].astype(str)), hide_index=True, width="stretch")
            st.caption("Raw strings are preserved exactly as in the source file. Quarantined values are excluded "
                       "(NaN) — never clipped or replaced by 0.")
        if not state.cleaning.rejected.empty:
            st.markdown("**Rejected rows** (unkeyable — missing station or invalid date)")
            st.dataframe(state.cleaning.rejected, hide_index=True, width="stretch")
    with tabs[3]:
        r = state.records
        multi = r[r.duplicated(["station", "timestamp"], keep=False)]
        st.markdown(f"**{len(state.cleaning.duplicates_removed)}** exact duplicates removed. "
                    f"**{multi[['station', 'timestamp']].drop_duplicates().shape[0]}** (station, timestamp) pairs "
                    "occur at different coordinates and are kept:")
        cols = ["record_id", "station", "timestamp", "lat", "lon"] + [c for c in r.columns if c.startswith("slno_")]
        st.dataframe(multi[cols].assign(timestamp=multi["timestamp"].astype(str)), hide_index=True, width="stretch")
        far = state.stations[state.stations["coordinate_spread_km"] > 1]
        if len(far):
            note("Stations whose coordinate variants are > 1 km apart (possible data-entry issue): "
                 + ", ".join(f"{n} ({d:.0f} km)" for n, d in zip(far["station_name"], far["coordinate_spread_km"])),
                 warn=True)
    with tabs[4]:
        st.dataframe(pd.DataFrame(a["tables"]).T.reset_index(names="table"), hide_index=True, width="stretch")
    with tabs[5]:
        show = state.stations.copy()
        for c in ("first_date", "last_date"):
            show[c] = show[c].dt.strftime("%Y-%m-%d")
        st.dataframe(show, hide_index=True, width="stretch")
        st.download_button("Download cleaned records (CSV)", state.records.to_csv(index=False).encode(),
                           "ecotrace_records_clean.csv", "text/csv")
    st.caption(f"Processed output folder: {PROCESSED_DIR.name}/ (records_clean.csv, stations.csv, river_edges.csv, "
               "quarantine.csv, incidents.csv, provenance.json)")
