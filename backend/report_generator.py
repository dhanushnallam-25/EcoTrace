"""CSV and Markdown/HTML investigation reports generated from live pipeline state."""
from __future__ import annotations

import html
import io
from datetime import datetime
from typing import List, Optional

import pandas as pd

from utils.helpers import fmt_value


def incidents_dataframe(incidents: List[dict], log=None) -> pd.DataFrame:
    rows = []
    for inc in incidents:
        c = inc["components"]
        row = {
            "incident_id": inc["incident_id"], "priority_score": inc["priority_score"],
            "priority_band": inc["priority_band"], "station_id": inc["station_id"],
            "station_name": inc["station_name"], "station_type": inc["station_type"],
            "district": inc["district"], "date": inc["date"], "primary_parameter": inc["parameter_label"],
            "value": inc["value"], "unit": inc["unit"], "criterion": inc["threshold_text"],
            "flag_type": inc["flag_type"], "downstream_stations": inc["downstream_count"],
            "c_severity": round(c["severity"], 3), "c_persistence": round(c["persistence"], 3),
            "c_downstream": round(c["downstream_reach"], 3), "c_anomaly": round(c["anomaly"], 3),
            "c_data_quality": round(c["data_quality"], 3),
            "source_table": inc["source_table"], "source_slno": inc["source_slno"],
            "violated_parameters": "; ".join(f"{v['label']}={v['value']:g}" for v in inc["violated_parameters"]),
            "lat": inc["lat"], "lon": inc["lon"],
        }
        if log is not None:
            e = log.get(inc["incident_id"])
            row["status"] = e["status"]
            row["notes"] = " | ".join(n["text"] for n in e.get("notes", []))
        rows.append(row)
    return pd.DataFrame(rows)


def incidents_csv(incidents: List[dict], log=None) -> bytes:
    buf = io.StringIO()
    incidents_dataframe(incidents, log).to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def markdown_report(state, top_n: int = 10, investigations: Optional[List[dict]] = None, log=None) -> str:
    a = state.cleaning.audit
    g = state.graph
    ranked = sorted(state.incidents, key=lambda i: -i["priority_score"])
    high = [i for i in ranked if i["priority_band"] == "High"]
    lines = [
        "# EcoTrace — River Pollution Investigation Report",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} from live pipeline state._",
        "",
        "> Screening report. Flags indicate readings that warrant follow-up; they do not prove a pollution source.",
        "",
        "## 1. Data provenance",
        f"- Water quality: {', '.join(f'`{p.name}`' for p in state.sources.values() if p is not None)}",
        f"- Records after cleaning/merge: **{a['merged_records']}** from **{a['stations']}** stations",
        f"- Date coverage: **{a['date_min']:%Y-%m-%d} → {a['date_max']:%Y-%m-%d}**",
        f"- Quarantined values: **{a['quarantined_values']}**; duplicates removed: **{a['duplicates_removed']}**; "
        f"same-station/time multi-coordinate pairs kept: **{a['same_station_timestamp_different_coordinates']}**",
        f"- Actively monitored parameters: {', '.join(state.cleaning.param_catalog[p]['label'] for p in a['active_params'])}",
        "",
        "## 2. River graph",
        f"- Vertices: **{g.get_vertex_count()}**, directed edges: **{g.get_edge_count()}**, "
        f"snapped river stations: **{state.matched_count}** (snap ≤ {state.config.snap_distance_km:g} km)",
        "",
        "## 3. Incident summary",
        f"- Flagged incidents: **{len(ranked)}**, high priority (≥ {state.config.high_priority_threshold:g}): **{len(high)}**",
        "",
        f"### Top {min(top_n, len(ranked))} incidents (MaxHeap order)",
        "",
        "| # | Incident | Score | Station | Date | Parameter | Value | Criterion | Downstream | SlNo |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k, inc in enumerate(ranked[:top_n], 1):
        lines.append(f"| {k} | {inc['incident_id']} | {inc['priority_score']:.1f} | {inc['station_name']} | "
                     f"{inc['date']} | {inc['parameter_label']} | {fmt_value(inc['value'], inc['unit'])} | "
                     f"{inc['threshold_text']} | {inc['downstream_count']} | {inc['source_slno']} |")
    if investigations:
        lines += ["", "## 4. Investigations"]
        for inv in investigations:
            inc = inv["incident"]
            lines += ["", f"### {inc['incident_id']} — {inc['station_name']} ({inc['date']})", ""]
            lines += [p for p in inv["narrative"]]
            if log is not None:
                e = log.get(inc["incident_id"])
                lines += ["", f"_Response status: {e['status']}_"]
                for n in e.get("notes", []):
                    lines.append(f"- {n['at']}: {n['text']}")
    lines += ["", "## Limitations",
              "- Screening signal only; requires field verification.",
              "- Monthly grab samples; transient events may be missed.",
              "- Graph edges derive from HydroRIVERS topology after spatial snapping; lakes are isolated.",
              "- Road routing unavailable (no road network supplied)."]
    return "\n".join(lines)


def html_report(markdown_text: str) -> str:
    """Minimal printable HTML wrapper (use the browser's Print → Save as PDF)."""
    body = []
    in_table = False
    for line in markdown_text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        esc = html.escape(line).replace("**", "")
        if line.startswith("### "):
            body.append(f"<h3>{esc[4:]}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{esc[3:]}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{esc[2:]}</h1>")
        elif line.startswith("- "):
            body.append(f"<li>{esc[2:]}</li>")
        elif line.startswith("&gt; "):
            body.append(f"<blockquote>{esc[5:]}</blockquote>")
        elif line.strip():
            body.append(f"<p>{esc}</p>")
    if in_table:
        body.append("</table>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;color:#0B192C;max-width:960px;margin:24px auto;padding:0 16px}"
           "h1,h2{color:#0D9488}table{border-collapse:collapse;width:100%;font-size:12px}"
           "td,th{border:1px solid #cbd5e1;padding:4px 6px}th{background:#0B192C;color:#fff}"
           "blockquote{border-left:4px solid #0D9488;margin:8px 0;padding:4px 12px;background:#f0fdfa}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>EcoTrace Report</title><style>{css}</style></head><body>{''.join(body)}</body></html>"
