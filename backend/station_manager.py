"""
Station registry: one row per monitoring-station *name*, with a deterministic ID,
a representative (modal) coordinate, a lake/river type inferred from the name, and
coordinate-variant bookkeeping.

Why name-based identity?  CPCB station names are the stable identifier in the source.
A few stations (e.g. Ulsoor Lake) carry two sampling coordinates; those readings are
kept as separate records, and the *most frequent* coordinate is used as the vertex
location. Stations whose coordinate variants are far apart are flagged so the UI can
warn the analyst.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from utils.constants import LAKE_KEYWORDS, RIVER_KEYWORDS
from utils.helpers import haversine_km

_LAKE_WORD = re.compile(r"\b(" + "|".join(["LAKE", "TANK", "TNAK", "POND", "KUNTE", "KERE", "KALYANI"]) + r")\b")
_LAKE_SUFFIX = re.compile(r"(KERE|KUNTE)\b")
_RIVER_WORD = re.compile(r"(\bRIVER\b|\bNALLA\b|\bNALA\b|\bDAM\b|\bBRIDGE\b|\bBDG\b|\bRESERVOIR\b|\bBARRAGE\b|"
                         r"\bBARAAGE\b|\bWEIR\b|\bINTAKE\b|\bCONFLUENCE\b|D/S|U/S|\bHOLE\b|\bJACKWELL\b|"
                         r"\bCAUSE ?WAY\b|\bGHAT\b|\bAT\b)")
_GROUNDWATER = re.compile(r"\b(BOREWELL|BORE WELL|WELL WATER|GROUND ?WATER)\b")


def classify_station(name: str) -> str:
    """'lake' | 'river' | 'unknown' from the station name (documented heuristic).

    Lake words are checked first, so "HESARAGHATTA TANK" -> lake while
    "ARKAVATHI AT HESARAGHATTA RESERVOIR" -> river. Groundwater (borewell) and names
    with no hydrological keyword -> unknown (they stay isolated in the graph).
    """
    n = str(name).upper()
    if _GROUNDWATER.search(n):
        return "unknown"
    if _LAKE_WORD.search(n) or _LAKE_SUFFIX.search(n):
        return "lake"
    if _RIVER_WORD.search(n):
        return "river"
    return "unknown"


def river_name_hint(name: str) -> Optional[str]:
    """Best-effort river name parsed from the station name (labelled as a *hint* in the UI)."""
    n = re.sub(r"\s+", " ", str(name).upper()).strip()
    n = re.sub(r"^(D/S|U/S) OF ", "", n)
    m = re.match(r"^([A-Z]+)(?: RIVER)?(?: AT| D/S| U/S| -|\b RIVER)", n)
    if m and m.group(1) not in {"BOREWELL"}:
        return m.group(1).title()
    m = re.search(r"\b([A-Z]+) RIVER\b", n)
    return m.group(1).title() if m else None


def build_station_table(records: pd.DataFrame) -> pd.DataFrame:
    """Aggregate merged records into a station registry and assign IDs ``KA-001``..."""
    rows = []
    for idx, (name, grp) in enumerate(sorted(records.groupby("station"), key=lambda kv: kv[0]), start=1):
        coords = grp.groupby(["lat", "lon"]).size().sort_values(ascending=False)
        coords = coords[[pd.notna(a) and pd.notna(b) for a, b in coords.index]]
        if len(coords):
            (lat, lon), _ = next(iter(coords.items()))
        else:
            lat = lon = float("nan")
        spread = 0.0
        if len(coords) > 1:
            spread = max(haversine_km(lat, lon, a, b) for a, b in coords.index)
        first = grp.iloc[0]
        rows.append({
            "station_id": f"KA-{idx:03d}",
            "station_name": name,
            "station_type": classify_station(name),
            "river_name_hint": river_name_hint(name),
            "district": first.get("district"),
            "tehsil": first.get("tehsil"),
            "lat": lat, "lon": lon,
            "coordinate_variants": int(len(coords)),
            "coordinate_spread_km": round(spread, 3),
            "n_records": int(len(grp)),
            "first_date": grp["timestamp"].min(),
            "last_date": grp["timestamp"].max(),
        })
    return pd.DataFrame(rows)


def attach_station_ids(records: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    lookup = dict(zip(stations["station_name"], stations["station_id"]))
    out = records.copy()
    out.insert(1, "station_id", out["station"].map(lookup))
    return out
