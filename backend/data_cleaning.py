"""
Cleaning & merging of CPCB water-quality tables.

Guarantees (each is unit-tested):
1. Numerics are parsed with ``pd.to_numeric(errors="coerce")``; a non-blank raw string
   that fails to parse (e.g. "3.16.2") is *quarantined* with its SlNo and raw text.
2. Physically impossible values (pH outside 0–14, negative concentrations) are set to
   NaN and quarantined — never clipped, never replaced by 0.
3. Missing values stay NaN. Nothing is zero-filled.
4. Each table is de-duplicated deterministically on (station, timestamp, lat, lon)
   (lowest SlNo kept) *before* merging, and the merge is validated ``one_to_one`` so a
   Cartesian blow-up is impossible.
5. Same-(station, timestamp) rows at *different* coordinates are kept (they are distinct
   sampling points) but counted and reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.schema_mapper import map_columns
from utils.constants import DEDUP_KEY, METADATA_ALIASES, PARAMETERS, PLAUSIBILITY_LIMITS
from utils.validation import validate_required_columns

BLANK_TOKENS = {"", "-", "--", "na", "n/a", "nan", "none", "null", "nd"}
TEXT_META = [c for c in METADATA_ALIASES if c not in ("slno", "lat", "lon", "timestamp")]
DATE_FORMATS = ("%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


@dataclass
class CleanTable:
    name: str
    data: pd.DataFrame
    parameters: List[str]
    schema_report: List[dict]
    quarantine: List[dict] = field(default_factory=list)
    rejected: List[dict] = field(default_factory=list)
    duplicates_removed: List[dict] = field(default_factory=list)
    raw_rows: int = 0


@dataclass
class CleaningResult:
    records: pd.DataFrame
    quarantine: pd.DataFrame
    rejected: pd.DataFrame
    duplicates_removed: pd.DataFrame
    schema_report: pd.DataFrame
    param_catalog: Dict[str, dict]
    active_params: List[str]
    unmeasured_params: List[str]
    audit: dict


# --------------------------------------------------------------------------- parsing helpers
def parse_timestamps(raw: pd.Series) -> pd.Series:
    """Try explicit day-first formats in turn (CPCB uses DD-MM-YYYY HH:MM); never guesses month-first."""
    text = raw.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        todo = out.isna()
        if not todo.any():
            break
        out.loc[todo] = pd.to_datetime(text[todo], format=fmt, errors="coerce")
    return out


def parse_numeric(raw: pd.Series):
    """Return (numeric series, blank mask, malformed mask). Malformed = non-blank but unparseable."""
    text = raw.astype(str).str.strip()
    blank = text.str.lower().isin(BLANK_TOKENS)
    numeric = pd.to_numeric(text.where(~blank), errors="coerce")
    malformed = (~blank) & numeric.isna()
    return numeric.astype(float), blank, malformed


def plausibility_bounds(param: str):
    if param in PLAUSIBILITY_LIMITS:
        return PLAUSIBILITY_LIMITS[param]
    return (0.0, None)   # every concentration / count is non-negative


# --------------------------------------------------------------------------- per-table cleaning
def clean_table(raw_df: pd.DataFrame, name: str) -> CleanTable:
    mapping, report = map_columns(list(raw_df.columns), table=name)
    missing = validate_required_columns({v: k for k, v in mapping.items()})
    if missing:
        raise ValueError(f"{name}: required columns not found: {missing}. "
                         f"Columns present: {list(raw_df.columns)}")
    df = raw_df.rename(columns=mapping).copy()
    params = [r["canonical"] for r in report if r["role"] == "parameter"]
    table = CleanTable(name=name, data=df, parameters=params, schema_report=report, raw_rows=len(df))

    # --- metadata -------------------------------------------------------------
    if "slno" in df.columns:
        df["slno"] = pd.to_numeric(df["slno"], errors="coerce").astype("Int64")
    else:
        df["slno"] = pd.array(range(1, len(df) + 1), dtype="Int64")
    for col in TEXT_META:
        if col in df.columns:
            s = df[col].astype(str).str.strip()
            df[col] = s.where(~s.str.lower().isin(BLANK_TOKENS))
    df["station"] = df["station"].str.replace(r"\s+", " ", regex=True).str.strip()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce").round(6)
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce").round(6)
    df["timestamp_raw"] = df["timestamp"].astype(str)
    df["timestamp"] = parse_timestamps(df["timestamp"])

    # --- reject rows that cannot be keyed ---------------------------------------
    bad_station = df["station"].isna()
    bad_time = df["timestamp"].isna()
    for idx in df.index[bad_station | bad_time]:
        reason = "missing station name" if bad_station[idx] else f"invalid date '{df.at[idx, 'timestamp_raw']}'"
        table.rejected.append({"table": name, "slno": _int(df.at[idx, "slno"]),
                               "station": df.at[idx, "station"], "reason": reason})
    df = df[~(bad_station | bad_time)].copy()

    # --- parameters: parse, flag malformed, quarantine impossible ----------------
    for p in params:
        numeric, _blank, malformed = parse_numeric(df[p])
        for idx in df.index[malformed]:
            table.quarantine.append(_q(name, df, idx, p, df.at[idx, p], "malformed numeric string"))
        lo, hi = plausibility_bounds(p)
        impossible = pd.Series(False, index=df.index)
        if lo is not None:
            impossible |= numeric < lo
        if hi is not None:
            impossible |= numeric > hi
        for idx in df.index[impossible]:
            bound = f"outside physically possible range [{lo}, {hi if hi is not None else '∞'}]"
            table.quarantine.append(_q(name, df, idx, p, df.at[idx, p], bound))
        df[p] = numeric.mask(impossible)          # NaN, never 0

    # --- deterministic de-duplication on the full key ---------------------------
    df = df.sort_values(["slno"], kind="mergesort")
    dup_mask = df.duplicated(subset=DEDUP_KEY, keep="first")
    for idx in df.index[dup_mask]:
        table.duplicates_removed.append({"table": name, "slno": _int(df.at[idx, "slno"]),
                                         "station": df.at[idx, "station"],
                                         "timestamp": df.at[idx, "timestamp"],
                                         "reason": "duplicate (station, timestamp, lat, lon) — lowest SlNo kept"})
    df = df[~dup_mask].reset_index(drop=True)
    table.data = df
    return table


def _int(v) -> Optional[int]:
    return None if pd.isna(v) else int(v)


def _q(table: str, df: pd.DataFrame, idx, param: str, raw_value, reason: str) -> dict:
    return {"table": table, "slno": _int(df.at[idx, "slno"]), "station": df.at[idx, "station"],
            "timestamp": df.at[idx, "timestamp"], "parameter": param, "raw_value": str(raw_value),
            "reason": reason}


# --------------------------------------------------------------------------- merge
def merge_tables(tables: List[CleanTable]) -> pd.DataFrame:
    """Outer-join cleaned tables on the dedup key with a one-to-one guarantee."""
    merged: Optional[pd.DataFrame] = None
    for t in tables:
        df = t.data.rename(columns={"slno": f"slno_{t.name}"})
        meta_cols = [c for c in TEXT_META if c in df.columns and c not in DEDUP_KEY]
        keep = DEDUP_KEY + [f"slno_{t.name}"] + meta_cols + t.parameters
        df = df[keep]
        if merged is None:
            merged = df
            continue
        overlap = [c for c in df.columns if c in merged.columns and c not in DEDUP_KEY]
        merged = merged.merge(df, on=DEDUP_KEY, how="outer", validate="one_to_one", suffixes=("", "__new"))
        for c in overlap:                 # coalesce shared metadata / parameters (first table wins)
            merged[c] = merged[c].combine_first(merged[f"{c}__new"])
            merged = merged.drop(columns=[f"{c}__new"])
    assert merged is not None
    merged = merged.sort_values(["station", "timestamp", "lat", "lon"], kind="mergesort").reset_index(drop=True)
    merged.insert(0, "record_id", [f"R{i + 1:05d}" for i in range(len(merged))])
    return merged


# --------------------------------------------------------------------------- orchestration
def clean_and_merge(raw_tables: Dict[str, pd.DataFrame], min_coverage: float = 0.10) -> CleaningResult:
    """Clean every supplied table (chemical / biological / physical) and merge them."""
    cleaned = [clean_table(df, name) for name, df in raw_tables.items() if df is not None]
    if not cleaned:
        raise ValueError("No water-quality tables supplied")
    records = merge_tables(cleaned)

    # --- parameter catalogue & active/unmeasured split -------------------------
    catalog: Dict[str, dict] = {}
    for t in cleaned:
        for row in t.schema_report:
            if row["role"] != "parameter":
                continue
            entry = catalog.setdefault(row["canonical"], {
                "key": row["canonical"], "label": row["label"], "unit": row["unit"],
                "raw_columns": [], "tables": []})
            entry["raw_columns"].append(row["raw_column"])
            entry["tables"].append(t.name)
    n = len(records)
    for key, entry in catalog.items():
        count = int(records[key].notna().sum()) if key in records else 0
        entry["count"] = count
        entry["coverage"] = count / n if n else 0.0
        entry["active"] = entry["coverage"] >= min_coverage
        entry["known"] = key in PARAMETERS
    active = sorted([k for k, e in catalog.items() if e["active"]], key=lambda k: -catalog[k]["coverage"])
    unmeasured = sorted([k for k, e in catalog.items() if not e["active"]], key=lambda k: catalog[k]["label"])

    quarantine = pd.DataFrame([q for t in cleaned for q in t.quarantine],
                              columns=["table", "slno", "station", "timestamp", "parameter", "raw_value", "reason"])
    rejected = pd.DataFrame([r for t in cleaned for r in t.rejected], columns=["table", "slno", "station", "reason"])
    dups = pd.DataFrame([d for t in cleaned for d in t.duplicates_removed],
                        columns=["table", "slno", "station", "timestamp", "reason"])
    schema = pd.DataFrame([r for t in cleaned for r in t.schema_report])

    st_time = records.groupby(["station", "timestamp"]).size()
    multi_coord_pairs = int((st_time > 1).sum())
    audit = {
        "tables": {t.name: {"raw_rows": t.raw_rows, "rows_after_cleaning": len(t.data),
                            "rejected": len(t.rejected), "duplicates_removed": len(t.duplicates_removed),
                            "quarantined_values": len(t.quarantine)} for t in cleaned},
        "merged_records": n,
        "stations": int(records["station"].nunique()),
        "unique_station_timestamp_keys": int(len(st_time)),
        "same_station_timestamp_different_coordinates": multi_coord_pairs,
        "date_min": records["timestamp"].min(),
        "date_max": records["timestamp"].max(),
        "quarantined_values": len(quarantine),
        "rejected_rows": len(rejected),
        "duplicates_removed": len(dups),
        "active_params": active,
        "unmeasured_params": unmeasured,
        "zero_filled_values": 0,   # by construction — asserted in tests
    }
    return CleaningResult(records=records, quarantine=quarantine, rejected=rejected, duplicates_removed=dups,
                          schema_report=schema, param_catalog=catalog, active_params=active,
                          unmeasured_params=unmeasured, audit=audit)


def row_completeness(records: pd.DataFrame, active_params: List[str]) -> pd.Series:
    """Fraction of *actively monitored* parameters present on each row (0..1)."""
    if not active_params:
        return pd.Series(np.nan, index=records.index)
    return records[active_params].notna().sum(axis=1) / len(active_params)
