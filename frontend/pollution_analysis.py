"""Pollution Analysis: thresholds, time series, distributions and the anomaly table."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.pollution_detection import station_summary, threshold_text
from frontend.common import build_state, require_state
from frontend.styles import SERIES, STATUS, TEAL, data_label, hero, note, plotly_layout, section
from utils.config import PipelineConfig
from utils.constants import LOG_SCALE_PARAMETERS
from utils.validation import validate_threshold


def render() -> None:
    state = require_state()
    hero("Pollution Analysis", "Rule-based CPCB screening + per-station robust anomaly detection (modified z / IQR)",
         data_label("Government data") + data_label("Derived"))
    params = state.analysis_params
    cat = state.cleaning.param_catalog
    p = st.selectbox("Parameter", params, format_func=lambda k: f"{cat[k]['label']} ({cat[k]['unit'] or 'unitless'})")
    spec = state.config.thresholds.get(p)
    unit = cat[p]["unit"]

    with st.expander("Configure CPCB screening thresholds", expanded=False):
        _threshold_editor(state)

    obs = state.obs[state.obs["parameter"] == p].copy()
    if spec:
        note(f"Criterion: <b>{threshold_text(spec, unit)}</b> — {spec.get('basis', '')}. "
             f"{int(obs['violated'].sum())} of {len(obs)} readings breach it; {int(obs['anomaly'].sum())} are "
             "statistical anomalies in the direction of worse water quality.")

    summ = station_summary(obs).sort_values(["violations", "anomalies"], ascending=False)
    default = summ["station_id"].head(3).tolist()
    names = dict(zip(state.stations["station_id"], state.stations["station_name"]))
    picked = st.multiselect("Stations for the time series (max 4)", sorted(obs["station_id"].unique(),
                            key=lambda s: names[s]), default=default, max_selections=4, format_func=lambda s: f"{names[s]} ({s})")

    left, right = st.columns([1.5, 1])
    with left:
        st.plotly_chart(_timeseries(obs, picked, names, spec, cat[p]["label"], unit, p), width="stretch")
    with right:
        st.plotly_chart(_distribution(obs, spec, cat[p]["label"], unit, p), width="stretch",
                        config={"displayModeBar": False})

    section("Station anomaly / violation table")
    f1, f2, f3 = st.columns(3)
    only_flag = f1.checkbox("Only stations with violations or anomalies", value=True)
    typ = f2.multiselect("Station type", ["river", "lake", "unknown"], default=["river", "lake", "unknown"])
    min_rate = f3.slider("Min violation rate", 0.0, 1.0, 0.0, 0.05)
    t = summ.merge(state.stations[["station_id", "station_type", "district"]], on="station_id")
    t = t[t["station_type"].isin(typ) & (t["violation_rate"] >= min_rate)]
    if only_flag:
        t = t[(t["violations"] > 0) | (t["anomalies"] > 0)]
    st.dataframe(t.drop(columns=["parameter"]), hide_index=True, width="stretch",
                 column_config={"violation_rate": st.column_config.ProgressColumn("violation rate", min_value=0,
                                                                                  max_value=1, format="%.2f")})

    section("Flagged readings")
    flagged = obs[obs["violated"] | obs["anomaly"]].sort_values(["exceedance", "anomaly_confidence"], ascending=False)
    cols = ["record_id", "station_id", "station", "timestamp", "value", "violated", "exceedance", "modified_z",
            "iqr_outlier", "z_outlier", "anomaly_confidence", "source_table", "source_slno"]
    st.dataframe(flagged[cols].assign(timestamp=flagged["timestamp"].dt.strftime("%Y-%m-%d")), hide_index=True,
                 width="stretch", height=320)
    st.caption("Modified z = 0.6745·(x − median)/MAD (Iglewicz & Hoaglin). Coliforms analysed on log10 scale. "
               f"Anomaly if bad-direction z > {state.config.modified_z_threshold} or beyond the Tukey fence "
               f"(k = {state.config.iqr_multiplier}); requires ≥ {state.config.min_obs_for_anomaly} readings.")


def _threshold_editor(state) -> None:
    cfg = state.config
    new = copy.deepcopy(cfg.thresholds)
    cols = st.columns(3)
    for k, (p, spec) in enumerate(cfg.thresholds.items()):
        c = cols[k % 3]
        c.markdown(f"**{state.cleaning.param_catalog.get(p, {}).get('label', p)}** · {spec['type']}")
        if spec["type"] in ("min", "range"):
            new[p]["min"] = c.number_input(f"{p} min", value=float(spec["min"]), key=f"thr_{p}_min", format="%.3f")
        if spec["type"] in ("max", "range"):
            new[p]["max"] = c.number_input(f"{p} max", value=float(spec["max"]), key=f"thr_{p}_max", format="%.3f")
    b1, b2 = st.columns(2)
    if b1.button("Apply thresholds & rebuild incidents", type="primary"):
        problems = [f"{p}: {msg}" for p, s in new.items() for ok, msg in [validate_threshold(s)] if not ok]
        if problems:
            st.error("; ".join(problems))
            return
        conf = PipelineConfig(**cfg.to_dict())
        conf.thresholds = new
        with st.spinner("Re-screening…"):
            build_state(st.session_state["sources"], conf)
        st.rerun()
    if b2.button("Restore CPCB defaults"):
        conf = PipelineConfig(**cfg.to_dict())
        conf.thresholds = PipelineConfig().thresholds
        build_state(st.session_state["sources"], conf)
        st.rerun()


def _timeseries(obs, picked, names, spec, label, unit, p) -> go.Figure:
    fig = go.Figure()
    for k, sid in enumerate(picked):
        s = obs[obs["station_id"] == sid].sort_values("timestamp")
        color = SERIES[k]
        fig.add_scatter(x=s["timestamp"], y=s["value"], mode="lines+markers", name=names[sid][:32],
                        line=dict(color=color, width=2), marker=dict(size=8, color=color, line=dict(color="#112240", width=2)),
                        customdata=np.stack([s["source_slno"].astype(str), s["violated"], s["anomaly"]], axis=-1),
                        hovertemplate="%{x|%Y-%m-%d}<br>" + label + ": %{y}<br>SlNo %{customdata[0]}"
                                      "<br>violates: %{customdata[1]} · anomaly: %{customdata[2]}<extra>%{fullData.name}</extra>")
        an = s[s["anomaly"]]
        if len(an):
            fig.add_scatter(x=an["timestamp"], y=an["value"], mode="markers", showlegend=k == 0,
                            name="statistical anomaly", legendgroup="anom",
                            marker=dict(symbol="diamond-open", size=15, color="#F1F5F9", line=dict(width=2)),
                            hoverinfo="skip")
    _threshold_lines(fig, spec, horizontal=True)
    fig.update_yaxes(title=f"{label} ({unit})" if unit else label, type="log" if p in LOG_SCALE_PARAMETERS else "linear")
    if not picked:
        fig.add_annotation(text="Select stations above", showarrow=False, font=dict(color="#94A3B8"))
    return plotly_layout(fig, f"{label} over time", height=400)


def _distribution(obs, spec, label, unit, p) -> go.Figure:
    v = obs["value"].astype(float)
    log = p in LOG_SCALE_PARAMETERS
    x = np.log10(v.clip(lower=1)) if log else v
    fig = go.Figure(go.Histogram(x=x, nbinsx=40, marker_color=TEAL, marker_line=dict(color="#112240", width=1),
                                 hovertemplate="%{x}<br>%{y} readings<extra></extra>"))
    if spec:
        for key in ("min", "max"):
            if key in spec and spec.get(key) is not None:
                val = np.log10(spec[key]) if log else spec[key]
                fig.add_vline(x=val, line_dash="dash", line_color=STATUS["High"],
                              annotation_text=f"criterion {key} {spec[key]:g}", annotation_font_color="#CBD5E1")
    fig.update_xaxes(title=(f"log10 {label}" if log else f"{label} ({unit})" if unit else label))
    fig.update_yaxes(title="readings")
    return plotly_layout(fig, "Distribution of all readings", height=400, legend_on=False)


def _threshold_lines(fig, spec, horizontal=True) -> None:
    if not spec:
        return
    for key in ("min", "max"):
        if key in spec and spec.get(key) is not None:
            fig.add_hline(y=spec[key], line_dash="dash", line_color=STATUS["High"], opacity=0.85,
                          annotation_text=f"CPCB {key} {spec[key]:g}", annotation_font_color="#CBD5E1",
                          annotation_position="top left")
