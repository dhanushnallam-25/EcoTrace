"""Downstream impact analysis built on BFS over the station graph."""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from backend.bfs import bfs_downstream


def downstream_counts(graph) -> Dict[str, int]:
    """BFS from every vertex: {station_id: #reachable downstream stations}. O(V·(V+E)).

    For a river forest each BFS only touches one downstream path, so this is cheap
    (V = 269 here); results are cached in the pipeline.
    """
    return {sid: bfs_downstream(graph, sid)["affected_count"] for sid in graph.vertices}


def nearest_reading(obs: pd.DataFrame, station_id: str, parameter: str, when: pd.Timestamp,
                    window_days: int = 45) -> Optional[dict]:
    """Closest-in-time observation of ``parameter`` at ``station_id`` within ±window_days."""
    sub = obs[(obs["station_id"] == station_id) & (obs["parameter"] == parameter)]
    if sub.empty:
        return None
    gap = (sub["timestamp"] - when).abs()
    i = gap.idxmin()
    if gap[i] > pd.Timedelta(days=window_days):
        return None
    r = sub.loc[i]
    return {"timestamp": r["timestamp"], "value": float(r["value"]), "violated": bool(r["violated"]),
            "anomaly": bool(r["anomaly"]), "gap_days": int(gap[i].days)}


def downstream_impact(graph, obs: pd.DataFrame, station_id: str, parameter: Optional[str] = None,
                      when: Optional[pd.Timestamp] = None) -> dict:
    res = bfs_downstream(graph, station_id)
    src_dist = graph.vertices[station_id].get("dist_dn_km")
    rows: List[dict] = []
    for sid in res["affected"]:
        v = graph.vertices[sid]
        row = {"station_id": sid, "station_name": v.get("station_name"), "hop_level": res["levels"][sid],
               "river_km_from_source": (round(src_dist - v["dist_dn_km"], 1)
                                        if src_dist is not None and v.get("dist_dn_km") is not None else None)}
        if parameter is not None and when is not None:
            near = nearest_reading(obs, sid, parameter, when)
            row.update({"reading_date": near["timestamp"].date() if near else None,
                        "reading_value": near["value"] if near else None,
                        "reading_violates": near["violated"] if near else None})
        rows.append(row)
    res["table"] = pd.DataFrame(rows)
    return res
