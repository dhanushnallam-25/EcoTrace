"""
Build the station-level DirectedRiverGraph from HydroRIVERS topology.

Algorithm
---------
1.  Every station becomes a vertex. Lakes / unknown-type stations are *not* snapped
    (unless configured) and remain isolated (in_degree = out_degree = 0).
2.  River-type stations are snapped (projected CRS, metres) to the nearest HydroRIVERS
    reach within ``snap_distance_km``. Farther stations stay isolated ("unmatched").
3.  For each snapped station we compute its distance to the basin outlet:
        station_dist_dn = DIST_DN_KM(reach) + (1 - f) * LENGTH_KM(reach)
    where f is the fractional position along the reach line (lines are digitised in
    flow direction — verified empirically: the end vertex touches NEXT_DOWN).
4.  Edges come *only* from the river topology, never from proximity:
      * stations on the same reach are chained in decreasing station_dist_dn order;
      * from the most-downstream station of a reach we follow NEXT_DOWN pointers
        (a hash-map walk, O(path length)) until the first reach that carries a
        station, and add one edge to that reach's most-upstream station.
    A reach-level walk that leaves the clipped bounding box or hits an outlet
    (NEXT_DOWN = 0) simply ends — no edge is invented.

Because river networks are in-trees, each vertex gets at most one downstream edge;
confluences produce in_degree > 1.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from backend.river_graph import DirectedRiverGraph
from utils.config import GEO_CRS, METRIC_CRS, PipelineConfig


def snap_stations(stations: pd.DataFrame, rivers, config: PipelineConfig) -> pd.DataFrame:
    """Return one row per station with match_status and (if matched) reach attributes."""
    import geopandas as gpd

    out = stations[["station_id", "station_name", "station_type", "lat", "lon"]].copy()
    out["match_status"] = out["station_type"].map(
        {"lake": "lake (isolated by design)", "unknown": "unknown type (isolated)"}).fillna("unmatched")
    for col in ("hyriv_id", "next_down", "main_riv", "ord_stra", "snap_distance_km",
                "reach_fraction", "dist_dn_km", "reach_length_km", "upland_skm", "dis_av_cms"):
        out[col] = pd.NA

    eligible = out["station_type"].eq("river")
    if config.snap_lake_stations:
        eligible |= out["station_type"].eq("lake")
    eligible &= out["lat"].notna() & out["lon"].notna()
    if rivers is None or len(rivers) == 0 or not eligible.any():
        return out

    pts = gpd.GeoDataFrame(out.loc[eligible, ["station_id"]],
                           geometry=gpd.points_from_xy(out.loc[eligible, "lon"], out.loc[eligible, "lat"]),
                           crs=GEO_CRS).to_crs(METRIC_CRS)
    riv = rivers.to_crs(METRIC_CRS)
    joined = gpd.sjoin_nearest(pts, riv, how="left", max_distance=config.snap_distance_km * 1000.0,
                               distance_col="snap_m")
    joined = joined.sort_values(["station_id", "snap_m", "HYRIV_ID"]).drop_duplicates("station_id")
    joined = joined[joined["HYRIV_ID"].notna()]

    riv_geom = dict(zip(riv["HYRIV_ID"], riv.geometry))
    updates = {}
    for row, pt in zip(joined.drop(columns="geometry").to_dict("records"), joined.geometry):
        rid = int(row["HYRIV_ID"])
        frac = float(riv_geom[rid].project(pt, normalized=True))
        length = float(row.get("LENGTH_KM") or 0.0)
        updates[row["station_id"]] = {
            "match_status": "matched", "hyriv_id": rid, "next_down": int(row["NEXT_DOWN"]),
            "main_riv": int(row["MAIN_RIV"]) if pd.notna(row.get("MAIN_RIV")) else pd.NA,
            "ord_stra": int(row["ORD_STRA"]) if pd.notna(row.get("ORD_STRA")) else pd.NA,
            "snap_distance_km": round(float(row["snap_m"]) / 1000.0, 3),
            "reach_fraction": round(frac, 4), "reach_length_km": length,
            # distance from station to basin outlet = reach pour-point distance + remaining reach length
            "dist_dn_km": round(float(row["DIST_DN_KM"]) + (1.0 - frac) * length, 3),
            "upland_skm": row.get("UPLAND_SKM"), "dis_av_cms": row.get("DIS_AV_CMS"),
        }
    out = out.astype({c: "object" for c in out.columns if c not in ("lat", "lon")})
    for col in ("match_status", "hyriv_id", "next_down", "main_riv", "ord_stra", "snap_distance_km",
                "reach_fraction", "reach_length_km", "dist_dn_km", "upland_skm", "dis_av_cms"):
        out[col] = [updates[s][col] if s in updates else cur for s, cur in zip(out["station_id"], out[col])]
    unmatched = eligible & out["match_status"].eq("unmatched")
    out.loc[unmatched, "match_status"] = f"unmatched (> {config.snap_distance_km:g} km from any reach)"
    return out


def build_river_graph(stations: pd.DataFrame, rivers, config: PipelineConfig,
                      measurements: Dict[str, dict] | None = None) -> Tuple[DirectedRiverGraph, pd.DataFrame, List[dict]]:
    """Return (graph, matches table, edge list with traced reach paths)."""
    matches = snap_stations(stations, rivers, config)
    graph = DirectedRiverGraph()
    meta = {r["station_id"]: r for r in stations.to_dict("records")}
    for m in matches.to_dict("records"):
        sid = m["station_id"]
        s = meta[sid]
        graph.add_vertex(
            sid, station_name=s["station_name"], lat=float(s["lat"]) if pd.notna(s["lat"]) else None,
            lon=float(s["lon"]) if pd.notna(s["lon"]) else None, river_name=s.get("river_name_hint"),
            hyriv_id=None if pd.isna(m["hyriv_id"]) else int(m["hyriv_id"]),
            main_riv=None if pd.isna(m["main_riv"]) else int(m["main_riv"]),
            dist_dn_km=None if pd.isna(m["dist_dn_km"]) else float(m["dist_dn_km"]),
            match_status=m["match_status"], station_type=s["station_type"], district=s.get("district"),
            snap_distance_km=None if pd.isna(m["snap_distance_km"]) else float(m["snap_distance_km"]),
            measurements=(measurements or {}).get(sid, {}),
        )

    matched = matches[matches["match_status"].eq("matched")].copy()
    if matched.empty or rivers is None:
        return graph, matches, []

    # reach -> stations on it, ordered upstream -> downstream (larger distance-to-outlet first)
    reach_stations: Dict[int, List[str]] = {}
    for rid, grp in matched.groupby("hyriv_id"):
        ordered = grp.sort_values(["dist_dn_km", "station_id"], ascending=[False, True])["station_id"].tolist()
        reach_stations[int(rid)] = ordered
    next_down = dict(zip(rivers["HYRIV_ID"].astype("int64"), rivers["NEXT_DOWN"].astype("int64")))
    dist_of = dict(zip(matched["station_id"], matched["dist_dn_km"].astype(float)))

    edges: List[dict] = []

    def _add(u: str, v: str, path: List[int], how: str) -> None:
        river_km = round(dist_of[u] - dist_of[v], 3)
        if graph.add_edge(u, v, river_km=river_km, reach_path=path, how=how):
            edges.append({"from": u, "to": v, "river_km": river_km, "reach_hops": max(len(path) - 1, 0),
                          "reach_path": path, "how": how,
                          "note": "co-located (order indeterminate)" if abs(river_km) < 0.05 else ""})

    for rid, chain in reach_stations.items():
        for a, b in zip(chain, chain[1:]):                      # same reach
            _add(a, b, [rid], "same reach")
        tail = chain[-1]
        path, cur, seen = [rid], next_down.get(rid, 0), {rid}
        while cur and cur in next_down and cur not in seen:    # NEXT_DOWN walk (hash lookups)
            seen.add(cur)
            path.append(cur)
            if cur in reach_stations:
                _add(tail, reach_stations[cur][0], path, "NEXT_DOWN walk")
                break
            cur = next_down[cur]
    return graph, matches, edges
