"""
End-to-end pipeline orchestration (ingest -> clean -> stations -> graph -> detect ->
score -> heap). The UI calls ``run_pipeline`` once per (files, config) combination and
caches the resulting ``PipelineState``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from backend.data_cleaning import CleaningResult, clean_and_merge
from backend.data_ingestion import load_hydrorivers, read_quality_csv
from backend.graph_builder import build_river_graph
from backend.impact_analysis import downstream_counts
from backend.incident_scoring import build_incidents
from backend.max_heap import MaxHeap
from backend.pollution_detection import detect
from backend.river_graph import DirectedRiverGraph
from backend.station_manager import attach_station_ids, build_station_table
from utils.config import KARNATAKA_BBOX, PipelineConfig
from utils.constants import ANALYSIS_PARAMETERS


@dataclass
class PipelineState:
    config: PipelineConfig
    sources: Dict[str, Optional[Path]]
    cleaning: CleaningResult
    records: pd.DataFrame
    stations: pd.DataFrame
    rivers: object                     # GeoDataFrame (clipped HydroRIVERS) or None
    river_cache: Optional[Path]
    river_cache_hit: bool
    graph: DirectedRiverGraph
    matches: pd.DataFrame
    edges: List[dict]
    obs: pd.DataFrame
    downstream: Dict[str, int]
    incidents: List[dict]
    timings: Dict[str, float] = field(default_factory=dict)

    @property
    def matched_count(self) -> int:
        return int((self.matches["match_status"] == "matched").sum())

    @property
    def analysis_params(self) -> List[str]:
        return [p for p in ANALYSIS_PARAMETERS if p in self.cleaning.active_params] + \
               [p for p in self.cleaning.active_params if p not in ANALYSIS_PARAMETERS]

    def build_heap(self) -> MaxHeap:
        return MaxHeap(self.incidents)

    def affected_downstream_stations(self, band: str = "High") -> int:
        """Distinct stations downstream of any incident in ``band`` (BFS union)."""
        from backend.bfs import bfs_downstream
        sources = {i["station_id"] for i in self.incidents if i["priority_band"] == band}
        affected = set()
        for s in sources:
            affected.update(bfs_downstream(self.graph, s)["affected"])
        return len(affected)


def run_pipeline(sources: Dict[str, Optional[Path]], config: Optional[PipelineConfig] = None,
                 progress=None) -> PipelineState:
    config = config or PipelineConfig()
    t: Dict[str, float] = {}

    def step(msg: str, frac: float) -> None:
        if progress:
            progress(msg, frac)

    step("Reading water-quality CSVs", 0.05)
    t0 = time.perf_counter()
    raw = {k: read_quality_csv(sources[k]) for k in ("chemical", "biological", "physical")
           if sources.get(k) is not None}
    if not raw:
        raise ValueError("At least one water-quality CSV is required")
    t["read_csv"] = time.perf_counter() - t0

    step("Cleaning, quarantining and de-duplicating", 0.15)
    t0 = time.perf_counter()
    cleaning = clean_and_merge(raw, min_coverage=config.active_param_min_coverage)
    stations = build_station_table(cleaning.records)
    records = attach_station_ids(cleaning.records, stations)
    t["clean_merge"] = time.perf_counter() - t0

    rivers, cache_path, cache_hit = None, None, False
    if sources.get("hydrorivers") is not None:
        step("Loading HydroRIVERS (clipped to Karnataka, cached)", 0.35)
        t0 = time.perf_counter()
        rivers, cache_path, cache_hit = load_hydrorivers(sources["hydrorivers"])
        t["load_rivers"] = time.perf_counter() - t0

    step("Snapping stations and building DirectedRiverGraph", 0.55)
    t0 = time.perf_counter()
    latest = _latest_measurements(records, cleaning.active_params)
    graph, matches, edges = build_river_graph(stations, rivers, config, latest)
    stations = stations.merge(matches[["station_id", "match_status", "hyriv_id", "main_riv", "ord_stra",
                                       "snap_distance_km", "dist_dn_km"]], on="station_id", how="left")
    stations["in_degree"] = stations["station_id"].map(graph.in_degree)
    stations["out_degree"] = stations["station_id"].map(graph.out_degree)
    t["build_graph"] = time.perf_counter() - t0

    step("Screening thresholds and anomalies", 0.7)
    t0 = time.perf_counter()
    obs = detect(records, cleaning.active_params, cleaning.param_catalog, config)
    t["detect"] = time.perf_counter() - t0

    step("BFS downstream reach + incident scoring", 0.85)
    t0 = time.perf_counter()
    down = downstream_counts(graph)
    incidents = build_incidents(records, obs, stations, down, cleaning.active_params, cleaning.param_catalog, config)
    t["score"] = time.perf_counter() - t0
    step("Done", 1.0)

    return PipelineState(config=config, sources=sources, cleaning=cleaning, records=records, stations=stations,
                         rivers=rivers, river_cache=cache_path, river_cache_hit=cache_hit, graph=graph,
                         matches=matches, edges=edges, obs=obs, downstream=down, incidents=incidents, timings=t)


def export_processed(state: "PipelineState", out_dir: Optional[Path] = None) -> Dict[str, Path]:
    """Write cleaned/derived tables to data/processed/ with a provenance JSON."""
    import json
    from datetime import datetime
    from utils.config import PROCESSED_DIR
    out_dir = Path(out_dir or PROCESSED_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "records": out_dir / "records_clean.csv", "stations": out_dir / "stations.csv",
        "edges": out_dir / "river_edges.csv", "quarantine": out_dir / "quarantine.csv",
        "incidents": out_dir / "incidents.csv", "provenance": out_dir / "provenance.json",
    }
    state.records.to_csv(paths["records"], index=False)
    state.stations.to_csv(paths["stations"], index=False)
    pd.DataFrame([{k: v for k, v in e.items() if k != "reach_path"} | {"reach_path": " ".join(map(str, e["reach_path"]))}
                  for e in state.edges]).to_csv(paths["edges"], index=False)
    state.cleaning.quarantine.to_csv(paths["quarantine"], index=False)
    from backend.report_generator import incidents_dataframe
    incidents_dataframe(state.incidents).to_csv(paths["incidents"], index=False)
    a = state.cleaning.audit
    prov = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "sources": {k: (p.name if p else None) for k, p in state.sources.items()},
        "labels": {
            "records_clean.csv": "Processed government data (CPCB manual surface-water monitoring, Karnataka)",
            "stations.csv": "Derived: station registry; type inferred from station name; snapping from HydroRIVERS v1.0",
            "river_edges.csv": "Derived: edges from HydroRIVERS NEXT_DOWN topology (not verified by field survey)",
            "quarantine.csv": "Raw source values excluded as malformed or physically impossible",
            "incidents.csv": "Derived screening flags (not regulatory findings)",
        },
        "processing": ["read CSV as raw strings", "schema auto-mapping", "day-first date parsing",
                       "numeric coercion + quarantine of malformed strings", "physical-plausibility quarantine",
                       "dedup on (station, timestamp, lat, lon)", "one-to-one outer merge chemical+biological",
                       f"HydroRIVERS clip to bbox (lon_min, lat_min, lon_max, lat_max) = {KARNATAKA_BBOX}",
                       f"snap river stations <= {state.config.snap_distance_km} km"],
        "audit": {k: (str(v) if not isinstance(v, (int, float, list, dict)) else v) for k, v in a.items()},
        "config": state.config.to_dict(),
    }
    paths["provenance"].write_text(json.dumps(prov, indent=2, default=str), encoding="utf-8")
    return paths


def _latest_measurements(records: pd.DataFrame, params: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {sid: {} for sid in records["station_id"].unique()}
    for p in params:
        sub = records[["station_id", "timestamp", p]].dropna().sort_values("timestamp")
        last = sub.groupby("station_id").tail(1)
        for sid, ts, v in zip(last["station_id"], last["timestamp"], last[p]):
            out[sid][p] = {"value": float(v), "date": ts.strftime("%Y-%m-%d")}
    return out
