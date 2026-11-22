"""
Response planning: triage status workflow, field notes and an action queue ordered by
the custom MaxHeap.

Status is persisted to ``data/processed/response_log.json`` so notes survive restarts.

Road routing: no road-network dataset was supplied, so travel routing (e.g. Dijkstra on
roads) is *unavailable*. River edges represent water flow, not drivable routes, and are
never used as driving directions.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from backend.max_heap import MaxHeap
from utils.config import RESPONSE_LOG_PATH
from utils.constants import INCIDENT_STATUSES

ROUTING_AVAILABLE = False
ROUTING_NOTICE = ("Road-network routing is unavailable: no road shapefile was provided. Dijkstra-based "
                  "travel planning would require a road graph (e.g. OpenStreetMap). River flow edges are "
                  "hydrological links and must NOT be used as driving routes.")


class ResponseLog:
    def __init__(self, path: Path = RESPONSE_LOG_PATH) -> None:
        self.path = Path(path)
        self.entries: Dict[str, dict] = {}
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.entries = {}

    def get(self, incident_id: str) -> dict:
        return self.entries.get(incident_id, {"status": "Pending", "notes": [], "assignee": ""})

    def status(self, incident_id: str) -> str:
        return self.get(incident_id)["status"]

    def update(self, incident_id: str, status: Optional[str] = None, note: Optional[str] = None,
               assignee: Optional[str] = None) -> dict:
        entry = self.get(incident_id)
        if status is not None:
            if status not in INCIDENT_STATUSES:
                raise ValueError(f"Invalid status {status}")
            entry["status"] = status
        if assignee is not None:
            entry["assignee"] = assignee
        if note:
            entry["notes"].append({"at": datetime.now().isoformat(timespec="seconds"), "text": note.strip()})
        entry["updated"] = datetime.now().isoformat(timespec="seconds")
        self.entries[incident_id] = entry
        self.save()
        return entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")


def recommended_actions(incident: dict) -> List[str]:
    p = incident["primary_parameter"]
    acts = []
    if incident["priority_band"] == "High":
        acts.append("Dispatch a field team for confirmatory re-sampling within 48 h (chain-of-custody).")
    else:
        acts.append("Schedule confirmatory sampling at the next routine visit.")
    if incident["downstream_count"] > 0:
        acts.append(f"Notify operators of the {incident['downstream_count']} downstream monitored point(s); "
                    "check for drinking-water intakes among them.")
    if p in ("total_coliform", "fecal_coliform"):
        acts.append("Inspect sewage outfalls / STP bypasses near the station; advise against bathing.")
    elif p in ("bod", "do"):
        acts.append("Survey for organic-load discharges (STP, food/agro industry); measure DO at dawn.")
    elif p == "ammonia_n":
        acts.append("Check sewage inflows and agricultural runoff; test for un-ionised ammonia (needs temp & pH).")
    elif p == "ph":
        acts.append("Check industrial effluent outfalls; verify with calibrated field pH meter.")
    if incident["station_type"] != "river":
        acts.append("Lake/tank: inspect inlet drains and encroachment; graph-based tracing is not applicable.")
    acts.append("Record verification outcome in the notes before resolving.")
    return acts


def action_queue(incidents: List[dict], log: ResponseLog, include_resolved: bool = False) -> List[dict]:
    """Order open incidents with the MaxHeap: score, then downstream count as a small tie-breaker."""
    heap = MaxHeap()
    for inc in incidents:
        st = log.status(inc["incident_id"])
        if st == "Resolved" and not include_resolved:
            continue
        heap.insert({**inc, "priority_score": inc["priority_score"] + 0.001 * min(inc["downstream_count"], 99),
                     "status": st})
    out = []
    while heap:
        item = heap.extract_max()
        item["priority_score"] = round(item["priority_score"], 2)
        out.append(item)
    return out
