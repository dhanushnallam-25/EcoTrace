"""
Explainable incident priority score (0–100).

    score = 100 * Σ_i w_i * c_i / Σ_i w_i        with every c_i in [0, 1]

| component        | default w | definition                                                         |
|------------------|-----------|--------------------------------------------------------------------|
| severity         | 0.35      | max normalised exceedance among the record's violated parameters  |
| persistence      | 0.20      | share of the station's sampled months in which the primary         |
|                  |           | parameter violated its threshold                                    |
| downstream_reach | 0.20      | min(BFS-reachable downstream stations / 5, 1)                       |
| anomaly          | 0.15      | modified-z / IQR anomaly confidence of the primary parameter        |
| data_quality     | 0.10      | completeness of the *actively monitored* parameters on that row     |

An incident is created for every record (station visit) that has at least one rule
violation or a bad-direction statistical anomaly. Each incident stores the full
component breakdown so the UI can explain every point of the score.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from backend.pollution_detection import threshold_text
from utils.config import PipelineConfig
from utils.constants import PARAMETERS

COMPONENT_LABELS = {
    "severity": "Severity (exceedance beyond CPCB criterion)",
    "persistence": "Persistence (share of months exceeding)",
    "downstream_reach": "Downstream reach (BFS-reachable stations)",
    "anomaly": "Statistical anomaly confidence",
    "data_quality": "Data quality (row completeness)",
}


def priority_band(score: float, high: float) -> str:
    if score >= high:
        return "High"
    if score >= high * 0.6:
        return "Medium"
    return "Low"


def compute_score(components: Dict[str, float], weights: Dict[str, float]) -> float:
    total_w = sum(max(w, 0.0) for w in weights.values())
    if total_w <= 0:
        return 0.0
    return round(100.0 * sum(max(weights.get(k, 0.0), 0.0) * components.get(k, 0.0) for k in weights) / total_w, 2)


def persistence_table(obs: pd.DataFrame) -> Dict[tuple, float]:
    """{(station_id, parameter): fraction of sampled months with >= 1 violation}."""
    o = obs[["station_id", "parameter", "timestamp", "violated"]].copy()
    o["month"] = o["timestamp"].dt.to_period("M")
    monthly = o.groupby(["station_id", "parameter", "month"])["violated"].any().reset_index()
    frac = monthly.groupby(["station_id", "parameter"])["violated"].mean()
    return frac.to_dict()


def build_incidents(records: pd.DataFrame, obs: pd.DataFrame, stations: pd.DataFrame,
                    downstream_counts: Dict[str, int], active_params: List[str],
                    param_catalog: Dict[str, dict], config: PipelineConfig) -> List[dict]:
    # Plain-dict lookups (hash maps) instead of per-row pandas indexing: O(I) overall.
    persist = persistence_table(obs)
    st_meta = {r["station_id"]: r for r in stations.to_dict("records")}
    slno_cols = [c for c in records.columns if c.startswith("slno_")]
    rec_cols = ["record_id", "lat", "lon"] + slno_cols + list(active_params)
    rec_meta = {r["record_id"]: r for r in records[rec_cols].to_dict("records")}
    n_active = max(len(active_params), 1)
    flagged = obs[obs["violated"] | obs["anomaly"]]
    cols = ["record_id", "station_id", "parameter", "value", "timestamp", "violated", "exceedance",
            "anomaly", "anomaly_confidence", "modified_z", "source_table", "source_slno"]
    by_record: Dict[str, List[dict]] = {}
    for row in flagged[cols].to_dict("records"):
        by_record.setdefault(row["record_id"], []).append(row)

    incidents: List[dict] = []
    for rid in sorted(by_record):
        rows = by_record[rid]
        viol = [r for r in rows if r["violated"]]
        if viol:
            primary = max(viol, key=lambda r: (r["exceedance"], r["anomaly_confidence"]))
        else:
            primary = max(rows, key=lambda r: r["anomaly_confidence"])
        p = primary["parameter"]
        sid = primary["station_id"]
        rec = rec_meta[rid]
        s = st_meta[sid]
        n_down = int(downstream_counts.get(sid, 0))
        comps = {
            "severity": max((r["exceedance"] for r in viol), default=0.0),
            "persistence": float(persist.get((sid, p), 0.0)),
            "downstream_reach": min(n_down / max(config.downstream_saturation, 1), 1.0),
            "anomaly": float(primary["anomaly_confidence"]),
            "data_quality": sum(1 for a in active_params if pd.notna(rec[a])) / n_active if active_params else 0.0,
        }
        score = compute_score(comps, config.weights)
        spec = config.thresholds.get(p, {})
        unit = (PARAMETERS.get(p) or {}).get("unit") or param_catalog.get(p, {}).get("unit", "")
        any_anom = any(r["anomaly"] for r in rows)
        flag_type = "threshold + anomaly" if viol and any_anom else "threshold" if viol else "anomaly only"
        ts = primary["timestamp"]
        incidents.append({
            "incident_id": f"INC-{rid[1:]}",
            "record_id": rid,
            "station_id": sid,
            "station_name": s["station_name"],
            "station_type": s["station_type"],
            "district": s.get("district"),
            "lat": float(rec["lat"]) if pd.notna(rec["lat"]) else None,
            "lon": float(rec["lon"]) if pd.notna(rec["lon"]) else None,
            "timestamp": ts,
            "date": ts.strftime("%Y-%m-%d"),
            "primary_parameter": p,
            "parameter_label": param_catalog.get(p, {}).get("label", p),
            "value": float(primary["value"]),
            "unit": unit,
            "threshold": spec,
            "threshold_text": threshold_text(spec, unit) if spec else "",
            "threshold_basis": spec.get("basis", ""),
            "source_table": primary["source_table"],
            "source_slno": None if pd.isna(primary["source_slno"]) else int(primary["source_slno"]),
            "slno_refs": {c.replace("slno_", ""): (None if pd.isna(rec[c]) else int(rec[c])) for c in slno_cols},
            "violated_parameters": [
                {"parameter": r["parameter"], "label": param_catalog.get(r["parameter"], {}).get("label", r["parameter"]),
                 "value": float(r["value"]), "exceedance": round(float(r["exceedance"]), 3)} for r in viol],
            "anomalous_parameters": [
                {"parameter": r["parameter"], "value": float(r["value"]), "modified_z": float(r["modified_z"]),
                 "confidence": float(r["anomaly_confidence"])} for r in rows if r["anomaly"]],
            "flag_type": flag_type,
            "downstream_count": n_down,
            "components": comps,
            "component_breakdown": explain_components(comps, config.weights),
            "priority_score": score,
            "priority_band": priority_band(score, config.high_priority_threshold),
            "label": s["station_name"],
        })
    return incidents


def explain_components(comps: Dict[str, float], weights: Dict[str, float]) -> List[dict]:
    total_w = sum(max(w, 0.0) for w in weights.values()) or 1.0
    rows = []
    for k, label in COMPONENT_LABELS.items():
        w = max(weights.get(k, 0.0), 0.0)
        rows.append({"component": k, "label": label, "value": round(comps.get(k, 0.0), 4),
                     "weight": w, "points": round(100.0 * w * comps.get(k, 0.0) / total_w, 2),
                     "max_points": round(100.0 * w / total_w, 2)})
    return rows


def rescore(incidents: List[dict], weights: Dict[str, float], high_threshold: float) -> List[dict]:
    """Recompute scores after a weight change without re-running detection (O(I))."""
    out = []
    for inc in incidents:
        new = dict(inc)
        new["priority_score"] = compute_score(inc["components"], weights)
        new["component_breakdown"] = explain_components(inc["components"], weights)
        new["priority_band"] = priority_band(new["priority_score"], high_threshold)
        out.append(new)
    return out
