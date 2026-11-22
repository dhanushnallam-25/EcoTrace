"""
Pollution screening: rule-based threshold checks + per-station statistical anomalies.

Two independent signals per (record, parameter):

1. **Rule violation** against configurable CPCB criteria. ``exceedance`` in [0, 1]
   expresses *how far* beyond the limit the value is:
     max-type (BOD, NH3-N):  (v/limit - 1) / (R - 1)            capped at 1
     max-type, log scale (coliforms): log10(v/limit) / log10(R)  capped at 1
     min-type (DO):          (limit - v) / limit
     range-type (pH):        distance outside [lo, hi] / delta
   where R (``full_severity_ratio``) is the multiple of the limit that counts as
   maximal severity.

2. **Statistical anomaly** relative to the station's own history:
     modified z = 0.6745 (x - median) / MAD          (Iglewicz & Hoaglin, 1993)
   with a Tukey IQR fence as a second opinion. Coliforms are analysed in log10 space.
   The score is *direction-aware*: only deviations toward worse water quality
   (low DO, high BOD, ...) count. Stations with fewer than ``min_obs`` readings
   are never called anomalous.

Missing values are skipped (never treated as 0).
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from utils.config import PipelineConfig
from utils.constants import BAD_DIRECTION, LOG_SCALE_PARAMETERS
from utils.helpers import clamp01


def evaluate_threshold(value: float, spec: dict, log_scale: bool = False) -> Tuple[bool, float]:
    """Return (violated, exceedance 0..1). NaN values are never violations."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False, 0.0
    kind = spec["type"]
    if kind == "max":
        limit = float(spec["max"])
        if value <= limit:
            return False, 0.0
        ratio = float(spec.get("full_severity_ratio", 5.0))
        if log_scale:
            return True, clamp01(math.log10(value / limit) / math.log10(ratio))
        return True, clamp01((value / limit - 1.0) / (ratio - 1.0))
    if kind == "min":
        limit = float(spec["min"])
        if value >= limit:
            return False, 0.0
        return True, clamp01((limit - value) / limit) if limit > 0 else 1.0
    if kind == "range":
        lo, hi = float(spec["min"]), float(spec["max"])
        if lo <= value <= hi:
            return False, 0.0
        delta = float(spec.get("full_severity_delta", 1.5))
        dist = lo - value if value < lo else value - hi
        return True, clamp01(dist / delta)
    raise ValueError(f"Unknown threshold type {kind}")


def threshold_text(spec: dict, unit: str = "") -> str:
    u = f" {unit}" if unit else ""
    if spec["type"] == "max":
        return f"≤ {spec['max']:g}{u}"
    if spec["type"] == "min":
        return f"≥ {spec['min']:g}{u}"
    return f"{spec['min']:g}–{spec['max']:g}{u}"


def to_long(records: pd.DataFrame, params: List[str], param_catalog: Dict[str, dict]) -> pd.DataFrame:
    """Melt wide records into one row per (record, parameter) with a source SlNo reference."""
    slno_cols = [c for c in records.columns if c.startswith("slno_")]
    id_cols = ["record_id", "station_id", "station", "timestamp", "lat", "lon"] + slno_cols
    long = records[id_cols + params].melt(id_vars=id_cols, value_vars=params, var_name="parameter",
                                          value_name="value")
    long = long[long["value"].notna()].copy()
    src = {p: (param_catalog.get(p, {}).get("tables") or ["?"])[0] for p in params}
    long["source_table"] = long["parameter"].map(src)
    long["source_slno"] = [row.get(f"slno_{t}") for row, t in
                           zip(long[slno_cols].to_dict("records"), long["source_table"])] if slno_cols else None
    return long.reset_index(drop=True)


def add_rule_flags(long: pd.DataFrame, thresholds: Dict[str, dict]) -> pd.DataFrame:
    violated, exceed = [], []
    for p, v in zip(long["parameter"], long["value"]):
        spec = thresholds.get(p)
        if spec is None:
            violated.append(False)
            exceed.append(0.0)
            continue
        flag, e = evaluate_threshold(float(v), spec, p in LOG_SCALE_PARAMETERS)
        violated.append(flag)
        exceed.append(e)
    long = long.copy()
    long["violated"] = violated
    long["exceedance"] = exceed
    return long


def add_anomaly_flags(long: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    """Vectorised per-(station, parameter) robust statistics."""
    long = long.copy()
    x = long["value"].astype(float)
    is_log = long["parameter"].isin(LOG_SCALE_PARAMETERS)
    long["x"] = np.where(is_log, np.log10(x.clip(lower=0) + 1.0), x)
    keys = ["station_id", "parameter"]
    g = long.groupby(keys)["x"]
    stats = pd.DataFrame({"n_obs": g.count(), "median": g.median(),
                          "q1": g.quantile(0.25), "q3": g.quantile(0.75)}).reset_index()
    long = long.merge(stats, on=keys, how="left")
    long["absdev"] = (long["x"] - long["median"]).abs()
    mad = long.groupby(keys)["absdev"].median().rename("mad").reset_index()
    long = long.merge(mad, on=keys, how="left").drop(columns=["absdev"])
    iqr = long["q3"] - long["q1"]

    # modified z-score; if MAD == 0 fall back to IQR-based scale; if both 0 -> 0
    scale = np.where(long["mad"] > 0, long["mad"] / 0.6745, np.where(iqr > 0, iqr / 1.349, np.nan))
    z = (long["x"] - long["median"]) / scale
    z = pd.Series(np.where(np.isnan(scale), 0.0, z), index=long.index)
    direction = long["parameter"].map(BAD_DIRECTION).fillna("both")
    bad_z = np.where(direction == "low", -z, np.where(direction == "high", z, z.abs()))
    long["modified_z"] = z.round(3)
    long["bad_direction_z"] = np.round(bad_z, 3)

    k = config.iqr_multiplier
    upper, lower = long["q3"] + k * iqr, long["q1"] - k * iqr
    beyond_upper, beyond_lower = long["x"] > upper, long["x"] < lower
    iqr_bad = np.where(direction == "low", beyond_lower,
                       np.where(direction == "high", beyond_upper, beyond_upper | beyond_lower))
    enough = long["n_obs"] >= config.min_obs_for_anomaly
    long["iqr_outlier"] = enough & iqr_bad
    long["z_outlier"] = enough & (long["bad_direction_z"] > config.modified_z_threshold)
    long["anomaly"] = long["iqr_outlier"] | long["z_outlier"]
    # confidence 0..1: half-credit for an IQR-only outlier, otherwise z / (2 * threshold)
    conf = np.clip(long["bad_direction_z"] / (2 * config.modified_z_threshold), 0, 1)
    conf = np.where(long["iqr_outlier"] & ~long["z_outlier"], np.maximum(conf, 0.5), conf)
    long["anomaly_confidence"] = np.where(enough, np.round(conf, 4), 0.0)
    return long.drop(columns=["x"])


def detect(records: pd.DataFrame, params: List[str], param_catalog: Dict[str, dict],
           config: PipelineConfig) -> pd.DataFrame:
    """Full screening table: one row per measured (record, parameter)."""
    params = [p for p in params if p in records.columns]
    long = to_long(records, params, param_catalog)
    long = add_rule_flags(long, config.thresholds)
    long = add_anomaly_flags(long, config)
    return long


def station_summary(obs: pd.DataFrame) -> pd.DataFrame:
    """Per-station, per-parameter counts of violations / anomalies (for the analysis table)."""
    agg = obs.groupby(["station_id", "station", "parameter"]).agg(
        n_obs=("value", "size"), violations=("violated", "sum"), anomalies=("anomaly", "sum"),
        median_value=("value", "median"), max_value=("value", "max"), min_value=("value", "min"),
        max_exceedance=("exceedance", "max"))
    agg["violation_rate"] = (agg["violations"] / agg["n_obs"]).round(3)
    return agg.reset_index()
