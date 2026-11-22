"""Pollution detection: malformed/impossible values, no zero-filling, thresholds, anomalies, scoring.

All rows are SYNTHETIC; the "SYN-KERE" row deliberately copies the defects of real CPCB
row SlNo 2300 (DO '3.16.2', Ammonia '0.41.83', pH 78.2) without using real data.
"""
import math

import numpy as np
import pandas as pd
import pytest

from backend.data_cleaning import clean_and_merge, parse_numeric
from backend.incident_scoring import build_incidents, compute_score, rescore
from backend.pollution_detection import add_anomaly_flags, detect, evaluate_threshold
from backend.station_manager import attach_station_ids, build_station_table
from utils.config import PipelineConfig
from utils.constants import DEFAULT_THRESHOLDS


@pytest.fixture
def cleaned(synthetic_chem_df, synthetic_bio_df):
    return clean_and_merge({"chemical": synthetic_chem_df, "biological": synthetic_bio_df})


def test_malformed_strings_quarantined_with_slno(cleaned):
    q = cleaned.quarantine
    bad = q[(q["slno"] == 4) & (q["reason"] == "malformed numeric string")]
    assert set(bad["parameter"]) == {"do", "ammonia_n"}
    assert set(bad["raw_value"]) == {"3.16.2", "0.41.83"}


def test_impossible_ph_quarantined_not_clipped(cleaned):
    q = cleaned.quarantine
    ph = q[(q["parameter"] == "ph") & (q["slno"] == 4)]
    assert len(ph) == 1 and ph.iloc[0]["raw_value"] == "78.2"
    row = cleaned.records[cleaned.records["slno_chemical"] == 4].iloc[0]
    assert math.isnan(row["ph"]) and math.isnan(row["do"]) and math.isnan(row["ammonia_n"])


def test_negative_bod_quarantined(cleaned):
    q = cleaned.quarantine
    assert ((q["parameter"] == "bod") & (q["raw_value"] == "-1")).any()


def test_missing_values_never_zero_filled(cleaned):
    recs = cleaned.records
    # SYN-KERE row 4: every chemical value was malformed/impossible -> NaN, not 0
    row = recs[recs["slno_chemical"] == 4].iloc[0]
    assert not (row[["ph", "do", "ammonia_n"]] == 0).any()
    # blank cadmium stays NaN everywhere
    assert recs["cadmium"].isna().all()
    assert cleaned.audit["zero_filled_values"] == 0


def test_parse_numeric_scientific_and_blank():
    num, blank, bad = parse_numeric(pd.Series(["5.4e+06", "", "-", "3.16.2", "7"]))
    assert num[0] == 5.4e6 and num[4] == 7
    assert list(blank) == [False, True, True, False, False]
    assert list(bad) == [False, False, False, True, False]


@pytest.mark.parametrize("param,value,violated", [
    ("ph", 7.0, False), ("ph", 9.5, True), ("ph", 5.0, True),
    ("do", 6.0, False), ("do", 2.0, True),
    ("bod", 3.0, False), ("bod", 12.0, True),
    ("total_coliform", 5000, False), ("total_coliform", 5.4e6, True),
])
def test_threshold_rules(param, value, violated):
    flag, e = evaluate_threshold(value, DEFAULT_THRESHOLDS[param], param.endswith("coliform"))
    assert flag is violated
    assert 0.0 <= e <= 1.0
    assert (e > 0) == violated


def test_nan_is_never_a_violation():
    assert evaluate_threshold(float("nan"), DEFAULT_THRESHOLDS["bod"]) == (False, 0.0)


def test_exceedance_monotonic():
    spec = DEFAULT_THRESHOLDS["bod"]
    es = [evaluate_threshold(v, spec)[1] for v in (4, 6, 9, 15, 100)]
    assert es == sorted(es) and es[-1] == 1.0


def test_direction_aware_anomaly():
    """SYNTHETIC: a high DO spike is *not* bad; a DO crash is."""
    vals = [6.0, 6.1, 5.9, 6.0, 6.2, 5.8, 6.0]
    rows = [{"station_id": "S", "parameter": "do", "value": v, "record_id": f"r{i}"} for i, v in enumerate(vals)]
    rows += [{"station_id": "S", "parameter": "do", "value": 12.0, "record_id": "hi"},
             {"station_id": "S", "parameter": "do", "value": 0.5, "record_id": "lo"}]
    out = add_anomaly_flags(pd.DataFrame(rows), PipelineConfig()).set_index("record_id")
    assert bool(out.loc["lo", "anomaly"]) is True
    assert bool(out.loc["hi", "anomaly"]) is False


def test_short_history_never_anomalous():
    rows = [{"station_id": "S", "parameter": "bod", "value": v, "record_id": str(i)} for i, v in enumerate([1, 1, 50])]
    out = add_anomaly_flags(pd.DataFrame(rows), PipelineConfig())
    assert not out["anomaly"].any()


def test_score_formula_and_bounds():
    w = PipelineConfig().weights
    assert compute_score({k: 1.0 for k in w}, w) == 100.0
    assert compute_score({k: 0.0 for k in w}, w) == 0.0
    assert compute_score({"severity": 1.0}, w) == pytest.approx(35.0)


def test_incidents_end_to_end_synthetic(cleaned):
    cfg = PipelineConfig()
    stations = build_station_table(cleaned.records)
    records = attach_station_ids(cleaned.records, stations)
    obs = detect(records, cleaned.active_params, cleaned.param_catalog, cfg)
    incidents = build_incidents(records, obs, stations, {}, cleaned.active_params, cleaned.param_catalog, cfg)
    assert incidents, "synthetic data contains threshold breaches"
    for inc in incidents:
        assert 0 <= inc["priority_score"] <= 100
        pts = sum(r["points"] for r in inc["component_breakdown"])
        assert pts == pytest.approx(inc["priority_score"], abs=0.05)
        assert inc["source_slno"] is not None
        assert not np.isnan(inc["value"])
    # rescoring with severity-only weights changes scores but not components
    re = rescore(incidents, {"severity": 1.0}, 60)
    assert all(r["components"] == i["components"] for r, i in zip(re, incidents))
    assert all(r["priority_score"] == pytest.approx(100 * i["components"]["severity"], abs=0.01)
               for r, i in zip(re, incidents))


def test_data_quality_uses_active_params_only(cleaned):
    """Unmeasured heavy metals (cadmium, COD) must not lower completeness."""
    cfg = PipelineConfig()
    stations = build_station_table(cleaned.records)
    records = attach_station_ids(cleaned.records, stations)
    obs = detect(records, cleaned.active_params, cleaned.param_catalog, cfg)
    incidents = build_incidents(records, obs, stations, {}, cleaned.active_params, cleaned.param_catalog, cfg)
    assert "cadmium" not in cleaned.active_params
    assert max(i["components"]["data_quality"] for i in incidents) > 0.5
