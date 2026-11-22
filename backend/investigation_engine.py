"""
Investigation engine: combines DFS (upstream candidates), BFS (downstream impact),
station history and threshold logic into an explainable, plain-English narrative.

Everything here is a *screening aid*. The narrative deliberately says "candidate",
"consistent with" and "requires field verification" — the data cannot prove a source.
"""
from __future__ import annotations

from typing import List

import pandas as pd

from backend.dfs import dfs_upstream
from backend.impact_analysis import downstream_impact, nearest_reading
from utils.helpers import fmt_value

LIMITATIONS = [
    "This is a screening signal, not proof of a pollution source or of a regulatory breach.",
    "CPCB samples are roughly monthly grab samples; short pollution events between visits are invisible.",
    "Upstream/downstream links come from HydroRIVERS topology after snapping stations within the "
    "configured distance; mis-snaps to a nearby tributary are possible.",
    "Lakes/tanks and unsnapped stations are isolated vertices — no upstream/downstream inference is made for them.",
    "Threshold defaults follow CPCB Designated-Best-Use criteria; Ammonia-N is compared to a free-ammonia "
    "criterion only as a proxy.",
    "Readings at different stations are matched by nearest sampling date (±45 days), not simultaneity.",
]

LIKELY_PATHWAYS = {
    "total_coliform": "untreated or partially treated sewage, livestock runoff",
    "fecal_coliform": "untreated sewage or faecal contamination",
    "bod": "organic load — sewage, food-processing or agro-industrial effluent",
    "do": "organic load consuming oxygen, eutrophication, low flow / stagnation",
    "ammonia_n": "sewage, fertiliser runoff, decomposing organic matter",
    "ph": "industrial/chemical discharge, algal blooms (high pH) or acidic effluent",
}


def investigate(incident: dict, graph, obs: pd.DataFrame, records: pd.DataFrame) -> dict:
    sid = incident["station_id"]
    p = incident["primary_parameter"]
    when = pd.Timestamp(incident["timestamp"])
    vertex = graph.vertices.get(sid, {})
    connected = sid in graph.vertices and not graph.is_isolated(sid)

    history = obs[(obs["station_id"] == sid) & (obs["parameter"] == p)].sort_values("timestamp")
    up = dfs_upstream(graph, sid)
    down = downstream_impact(graph, obs, sid, p, when)

    upstream_rows: List[dict] = []
    src_dist = vertex.get("dist_dn_km")
    for cand in up["candidates"]:
        v = graph.vertices[cand]
        near = nearest_reading(obs, cand, p, when)
        upstream_rows.append({
            "station_id": cand, "station_name": v.get("station_name"), "dfs_depth": up["depth"][cand],
            "river_km_upstream": (round(v["dist_dn_km"] - src_dist, 1)
                                  if src_dist is not None and v.get("dist_dn_km") is not None else None),
            "reading_date": near["timestamp"].date() if near else None,
            "reading_value": near["value"] if near else None,
            "also_violates": near["violated"] if near else None,
            "difference_vs_incident": round(incident["value"] - near["value"], 3) if near else None,
        })
    upstream_table = pd.DataFrame(upstream_rows)

    narrative = _narrative(incident, vertex, connected, up, upstream_table, down, history)
    return {"incident": incident, "history": history, "dfs": up, "bfs": down,
            "upstream_table": upstream_table, "downstream_table": down["table"],
            "narrative": narrative, "limitations": LIMITATIONS + up["caveats"][1:2]}


def _worse_ratio(param: str, value: float, max_up: float, min_up: float):
    """How many times worse the incident value is than the worst upstream value (None if undefined)."""
    if param == "do":                       # lower is worse
        return (min_up / value) if value > 0 else None
    if param == "ph":
        return None                         # ratios are meaningless on a log scale centred at 7
    return (value / max_up) if max_up > 0 else None


def _narrative(inc, vertex, connected, up, upstream_table, down, history) -> List[str]:
    unit = inc.get("unit", "")
    paras = []
    refs = ", ".join(f"{t} SlNo {n}" for t, n in inc.get("slno_refs", {}).items() if n is not None)
    paras.append(
        f"On {inc['date']}, **{inc['station_name']}** ({inc['station_id']}, {inc['station_type']}) recorded "
        f"**{inc['parameter_label']} = {fmt_value(inc['value'], unit)}** against a screening criterion of "
        f"{inc['threshold_text'] or 'n/a'} ({inc['threshold_basis'] or 'no rule'}). Source rows: {refs or 'n/a'}. "
        f"Flag type: {inc['flag_type']}; priority score {inc['priority_score']:.1f}/100 ({inc['priority_band']}).")

    n_hist = len(history)
    n_viol = int(history["violated"].sum()) if n_hist else 0
    if n_hist:
        paras.append(
            f"Across {n_hist} sampled readings of this parameter at the station, {n_viol} breached the criterion "
            f"(persistence component {inc['components']['persistence']:.2f}). "
            + ("The problem appears **chronic** rather than a one-off event."
               if inc["components"]["persistence"] >= 0.5 else
               "The breach is **intermittent**, which makes a discrete event more plausible."))
    if inc["anomalous_parameters"]:
        z = max(a["modified_z"] for a in inc["anomalous_parameters"])
        paras.append(f"Relative to the station's own history the reading is statistically unusual "
                     f"(modified z up to {z:.1f}).")

    if not connected:
        reason = vertex.get("match_status", "not snapped to a river reach")
        paras.append(
            f"This station is an isolated vertex in the river graph ({reason}). No upstream or downstream "
            "monitoring stations can be linked, so investigation should focus on the immediate catchment "
            f"(inflow drains, outfalls, land use). Typical pathways for this parameter: "
            f"{LIKELY_PATHWAYS.get(inc['primary_parameter'], 'see parameter guidance')}.")
        return paras

    if up["candidate_count"] == 0:
        paras.append("DFS found **no monitored upstream station** — this is the most upstream monitored point on "
                     "its branch, so the cause lies somewhere in the unmonitored catchment above it.")
    else:
        with_data = upstream_table.dropna(subset=["reading_value"]) if not upstream_table.empty else upstream_table
        also = with_data[with_data["also_violates"] == True] if len(with_data) else with_data  # noqa: E712
        clean = with_data[with_data["also_violates"] == False] if len(with_data) else with_data  # noqa: E712
        txt = (f"DFS traced **{up['candidate_count']} upstream candidate station(s)** across "
               f"{up['branch_count']} branch path(s). {len(with_data)} had a reading within ±45 days. ")
        if len(with_data) == 0:
            txt += "Without contemporaneous upstream readings no upstream comparison is possible."
        elif len(also) == 0:
            nearest = clean.sort_values("dfs_depth").iloc[0]
            txt += (f"None of them breached the criterion, so the signal is **consistent with an input between "
                    f"{nearest['station_name']} and this station**"
                    + (f" (≈{abs(nearest['river_km_upstream']):.0f} river-km)" if pd.notna(nearest['river_km_upstream']) else "")
                    + " — a candidate stretch for field inspection.")
        else:
            names = ", ".join(also.sort_values("dfs_depth")["station_name"].head(3))
            max_up = float(with_data["reading_value"].max())
            ratio = _worse_ratio(inc["primary_parameter"], inc["value"], max_up, float(with_data["reading_value"].min()))
            txt += f"{len(also)} upstream station(s) also breached it ({names}). "
            if ratio is not None and ratio >= 2.0:
                txt += (f"However, this reading is about **{ratio:.0f}× worse** than the worst contemporaneous "
                        "upstream reading, which is consistent with an **additional local input** between the "
                        "nearest upstream station and this one, on top of a degraded upstream baseline.")
            else:
                txt += ("Upstream readings are of similar magnitude, suggesting the problem may originate further "
                        "upstream or be basin-wide; investigation should start at the most upstream breaching station.")
        paras.append(txt)

    if down["affected_count"]:
        tbl = down["table"]
        breach = int((tbl["reading_violates"] == True).sum()) if "reading_violates" in tbl else 0  # noqa: E712
        paras.append(f"BFS shows **{down['affected_count']} monitored station(s) downstream** "
                     f"(up to {down['max_level']} hops); {breach} of them also breached the criterion near this date. "
                     "Downstream water users (intakes listed among these stations) should be prioritised for notification.")
    else:
        paras.append("BFS found no monitored station downstream inside the study area.")
    paras.append(f"Typical pathways to check in the field: {LIKELY_PATHWAYS.get(inc['primary_parameter'], 'n/a')}.")
    return paras
