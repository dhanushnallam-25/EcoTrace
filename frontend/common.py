"""Shared UI state helpers (pipeline caching, rescoring) and Folium map builders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import folium
import pandas as pd
import streamlit as st

from backend.data_ingestion import discover_default_files
from backend.incident_scoring import rescore
from backend.max_heap import MaxHeap
from backend.pipeline import PipelineState, export_processed, run_pipeline
from frontend.styles import (BFS_COLOR, DFS_COLOR, MUTED, SOURCE_COLOR, STATION_COLORS, TEAL, TEXT)
from utils.config import PipelineConfig
from utils.helpers import files_fingerprint


# --------------------------------------------------------------------------- pipeline state
@st.cache_resource(show_spinner=False, max_entries=4)
def _cached_pipeline(source_items: tuple, fingerprint: str, config_json: str) -> PipelineState:
    sources = {k: (Path(v) if v else None) for k, v in source_items}
    config = PipelineConfig(**json.loads(config_json))
    state = run_pipeline(sources, config)
    try:
        export_processed(state)
    except OSError:
        pass                                   # read-only disk: exports are optional
    return state


def build_state(sources: Dict[str, Optional[Path]], config: PipelineConfig) -> PipelineState:
    items = tuple(sorted((k, str(v) if v else "") for k, v in sources.items()))
    fp = files_fingerprint([v for _, v in sorted(sources.items())])
    state = _cached_pipeline(items, fp, json.dumps(config.to_dict(), sort_keys=True))
    st.session_state["sources"] = sources
    st.session_state["config"] = config
    st.session_state["state"] = state
    reset_heap(state)
    return state


def load_defaults(config: Optional[PipelineConfig] = None) -> PipelineState:
    found = discover_default_files()
    if found.get("chemical") is None and found.get("biological") is None:
        raise FileNotFoundError("No default CPCB CSVs found in files/")
    return build_state(found, config or st.session_state.get("config") or PipelineConfig())


def get_state() -> Optional[PipelineState]:
    return st.session_state.get("state")


def require_state() -> PipelineState:
    state = get_state()
    if state is None:
        st.info("No dataset loaded yet. Open **Dataset Management** or click "
                "**Load Default Karnataka CPCB + HydroRIVERS Dataset** in the sidebar.")
        st.stop()
    return state


def current_weights(state: PipelineState) -> dict:
    return st.session_state.get("weights") or dict(state.config.weights)


def incidents(state: PipelineState) -> List[dict]:
    """Incidents rescored with the session's weights (detection itself is not re-run)."""
    w = current_weights(state)
    if w == state.config.weights:
        return state.incidents
    key = ("rescored", id(state), json.dumps(w, sort_keys=True))
    if st.session_state.get("_rescored_key") != key:
        st.session_state["_rescored"] = rescore(state.incidents, w, state.config.high_priority_threshold)
        st.session_state["_rescored_key"] = key
    return st.session_state["_rescored"]


def reset_heap(state: PipelineState) -> MaxHeap:
    heap = MaxHeap(incidents(state))
    st.session_state["heap"] = heap
    st.session_state["heap_log"] = []
    return heap


def get_heap(state: PipelineState) -> MaxHeap:
    if "heap" not in st.session_state:
        return reset_heap(state)
    return st.session_state["heap"]


def incident_lookup(state: PipelineState) -> Dict[str, dict]:
    return {i["incident_id"]: i for i in incidents(state)}


def incident_option_label(inc: dict) -> str:
    return (f"{inc['incident_id']} · {inc['priority_score']:.1f} · {inc['station_name'][:40]} · "
            f"{inc['parameter_label']} · {inc['date']}")


def station_type_key(row) -> str:
    if row.get("match_status") == "matched":
        return "matched"
    if row.get("station_type") == "lake":
        return "lake"
    if row.get("station_type") == "river":
        return "unmatched"
    return "unknown"


# --------------------------------------------------------------------------- maps
@st.cache_data(show_spinner=False, max_entries=4)
def river_geojson(_rivers, cache_key: str, min_order: int, extra_ids: tuple) -> str:
    """Simplified GeoJSON of major reaches (Strahler >= min_order) + reaches on graph edges."""
    if _rivers is None:
        return ""
    sel = _rivers[(_rivers["ORD_STRA"] >= min_order) | (_rivers["HYRIV_ID"].isin(set(extra_ids)))]
    sel = sel[["HYRIV_ID", "ORD_STRA", "geometry"]].copy()
    sel["geometry"] = sel.geometry.simplify(0.002)
    return sel.to_json()


def base_map(state: PipelineState, center=None, zoom: int = 7, min_order: int = 5) -> folium.Map:
    m = folium.Map(location=center or [14.8, 76.3], zoom_start=zoom, tiles=None, control_scale=True,
                   prefer_canvas=True)
    # Keyless basemaps (CartoDB now requires an API key).
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors", name="Dark canvas (Esri)",
        max_zoom=16).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    if state.rivers is not None:
        edge_reaches = tuple(sorted({r for e in state.edges for r in e["reach_path"]}))
        gj = river_geojson(state.rivers, str(state.river_cache), min_order, edge_reaches)
        folium.GeoJson(
            gj, name=f"HydroRIVERS reaches (order ≥ {min_order} + graph paths)",
            style_function=lambda f: {"color": "#38BDF8", "weight": 0.6 + 0.35 * max(f["properties"]["ORD_STRA"] - 4, 0),
                                      "opacity": 0.55},
            tooltip=folium.GeoJsonTooltip(fields=["HYRIV_ID", "ORD_STRA"], aliases=["HYRIV_ID", "Strahler order"]),
        ).add_to(m)
    return m


def _edge_coords(state: PipelineState, edge: dict) -> List[list]:
    """Coordinates along the HydroRIVERS reaches of an edge (lat, lon), from u's station to v's station."""
    u, v = state.graph.vertices[edge["from"]], state.graph.vertices[edge["to"]]
    coords = [[u["lat"], u["lon"]]]
    if state.rivers is not None and len(edge["reach_path"]) > 1:
        geoms = _reach_geoms(state)
        for rid in edge["reach_path"][1:-1]:
            g = geoms.get(rid)
            if g is not None:
                line = g.geoms[0] if hasattr(g, "geoms") else g
                coords.extend([[y, x] for x, y in line.coords[::3]])
    coords.append([v["lat"], v["lon"]])
    return coords


def _reach_geoms(state: PipelineState) -> dict:
    key = f"_reach_geoms_{id(state)}"
    if key not in st.session_state:
        needed = {r for e in state.edges for r in e["reach_path"]}
        sub = state.rivers[state.rivers["HYRIV_ID"].isin(needed)]
        st.session_state[key] = dict(zip(sub["HYRIV_ID"], sub.geometry))
    return st.session_state[key]


def add_edges(m: folium.Map, state: PipelineState, edges: Iterable[dict], color: str = TEAL, weight: float = 2.0,
              animate: bool = False, name: str = "Directed station edges") -> None:
    from folium import plugins
    fg = folium.FeatureGroup(name=name)
    for e in edges:
        coords = _edge_coords(state, e)
        tip = (f"{e['from']} → {e['to']} · {e['river_km']:.1f} river-km · {e['reach_hops']} reach hops"
               + (f" · {e['note']}" if e.get("note") else ""))
        if animate:
            plugins.AntPath(coords, color=color, weight=weight + 1, delay=900, dash_array=[8, 18],
                            pulse_color="#FFFFFF", tooltip=tip).add_to(fg)
        else:
            folium.PolyLine(coords, color=color, weight=weight, opacity=0.9, tooltip=tip).add_to(fg)
    fg.add_to(m)


def add_station_markers(m: folium.Map, state: PipelineState, highlight: Optional[Dict[str, str]] = None,
                        labels: Optional[Dict[str, str]] = None, only: Optional[set] = None,
                        name: str = "Monitoring stations") -> None:
    fg = folium.FeatureGroup(name=name)
    for row in state.stations.to_dict("records"):
        if pd.isna(row["lat"]) or (only is not None and row["station_id"] not in only):
            continue
        key = station_type_key(row)
        color = STATION_COLORS[key]
        radius, weight, line = 5, 1, "#0B192C"
        if highlight and row["station_id"] in highlight:
            color = highlight[row["station_id"]]
            radius, weight, line = 9, 2, TEXT
        extra = (labels or {}).get(row["station_id"], "")
        tip = (f"<b>{row['station_name']}</b><br>{row['station_id']} · {row['station_type']} · {row['match_status']}"
               f"<br>in/out degree: {row['in_degree']}/{row['out_degree']}" + (f"<br>{extra}" if extra else ""))
        folium.CircleMarker([row["lat"], row["lon"]], radius=radius, color=line, weight=weight, fill=True,
                            fill_color=color, fill_opacity=0.95, tooltip=tip).add_to(fg)
    fg.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)   # stations are added last on every map


def station_legend_items():
    return [(STATION_COLORS["matched"], "River station snapped to HydroRIVERS (graph vertex with edges)"),
            (STATION_COLORS["unmatched"], "River station not snapped (> snap distance)"),
            (STATION_COLORS["lake"], "Lake / tank (isolated by design)"),
            (STATION_COLORS["unknown"], "Unknown type (isolated)"),
            (TEAL, "Directed edge (flow u → v)")]


__all__ = ["BFS_COLOR", "DFS_COLOR", "SOURCE_COLOR", "MUTED"]
