"""Ingestion, schema mapping, de-duplication and merging (SYNTHETIC CSV fixtures)."""
import pandas as pd

from backend.data_cleaning import clean_and_merge, clean_table, parse_timestamps
from backend.data_ingestion import discover_default_files, read_quality_csv
from backend.schema_mapper import map_columns
from backend.station_manager import build_station_table, classify_station


def test_schema_mapping_aliases():
    mapping, report = map_columns(["SlNo", "Station", "Latitude", "Longitude", "Data Acquisition Time",
                                   "Potential of Hydrogen (pH)", "Amonia N (mgN/L)", "Mystery Ion (mg/L)"])
    assert mapping["Potential of Hydrogen (pH)"] == "ph"
    assert mapping["Amonia N (mgN/L)"] == "ammonia_n"
    assert mapping["Data Acquisition Time"] == "timestamp"
    assert mapping["Mystery Ion (mg/L)"] == "mystery_ion"
    unknown = [r for r in report if r["raw_column"] == "Mystery Ion (mg/L)"][0]
    assert unknown["role"] == "parameter" and unknown["unit"] == "mg/L"


def test_schema_mapping_is_case_and_punctuation_insensitive():
    mapping, _ = map_columns(["STATION", "latitude", "LONGITUDE", "data_acquisition_time", "DISSOLVED OXYGEN(mg/l)"])
    assert mapping["DISSOLVED OXYGEN(mg/l)"] == "do"
    assert mapping["STATION"] == "station"


def test_exact_duplicates_removed_deterministically(synthetic_chem_df):
    t = clean_table(synthetic_chem_df, "chemical")
    assert len(t.duplicates_removed) == 1
    assert t.duplicates_removed[0]["slno"] == 3          # lowest SlNo (2) kept
    assert 2 in set(t.data["slno"]) and 3 not in set(t.data["slno"])


def test_same_station_time_different_coordinates_kept(synthetic_chem_df, synthetic_bio_df):
    res = clean_and_merge({"chemical": synthetic_chem_df, "biological": synthetic_bio_df})
    kere = res.records[(res.records["station"] == "SYN-KERE") &
                       (res.records["timestamp"] == pd.Timestamp("2021-09-10 08:30"))]
    assert len(kere) == 2                                  # two coordinates -> two records
    assert res.audit["same_station_timestamp_different_coordinates"] == 1


def test_merge_is_one_to_one_no_cartesian(synthetic_chem_df, synthetic_bio_df):
    res = clean_and_merge({"chemical": synthetic_chem_df, "biological": synthetic_bio_df})
    # 7 raw rows - 1 duplicate - 1 invalid date = 5 records in each table -> 5 merged rows
    assert len(res.records) == 5
    assert res.records[["station", "timestamp", "lat", "lon"]].duplicated().sum() == 0
    assert {"slno_chemical", "slno_biological"} <= set(res.records.columns)
    assert (res.records["slno_chemical"] == res.records["slno_biological"]).all()


def test_invalid_dates_rejected_not_guessed(synthetic_chem_df):
    t = clean_table(synthetic_chem_df, "chemical")
    assert any("invalid date" in r["reason"] and r["slno"] == 7 for r in t.rejected)
    parsed = parse_timestamps(pd.Series(["01-02-2021 08:30", "2021-03-04", "garbage"]))
    assert parsed[0] == pd.Timestamp("2021-02-01 08:30")    # day-first, never month-first
    assert parsed[1] == pd.Timestamp("2021-03-04")
    assert pd.isna(parsed[2])


def test_metadata_dash_becomes_missing(synthetic_chem_df):
    t = clean_table(synthetic_chem_df, "chemical")
    assert t.data["river"].isna().all()


def test_active_vs_unmeasured_parameters(synthetic_chem_df, synthetic_bio_df):
    res = clean_and_merge({"chemical": synthetic_chem_df, "biological": synthetic_bio_df}, min_coverage=0.10)
    assert "cadmium" in res.unmeasured_params and "cod" in res.unmeasured_params
    assert {"ph", "do", "bod"} <= set(res.active_params)


def test_station_registry_and_classification(synthetic_chem_df, synthetic_bio_df):
    res = clean_and_merge({"chemical": synthetic_chem_df, "biological": synthetic_bio_df})
    st = build_station_table(res.records)
    assert list(st["station_id"]) == ["KA-001", "KA-002"]
    kere = st[st["station_name"] == "SYN-KERE"].iloc[0]
    assert kere["coordinate_variants"] == 2 and kere["lat"] == 12.5     # modal coordinate
    assert classify_station("CAUVERY AT KRS DAM MANDYA") == "river"
    assert classify_station("HESARAGHATTA TANK") == "lake"
    assert classify_station("UTTARAHALLI DORAIKERE") == "lake"
    assert classify_station("VENKATPUR RIVER NR KADIVINAKATTE DAM") == "river"
    assert classify_station("BOREWELL WATER NEAR SCHOOL") == "unknown"


def test_read_csv_keeps_raw_strings(tmp_path, synthetic_chem_df):
    p = tmp_path / "syn_chemical.csv"
    synthetic_chem_df.to_csv(p, index=False)
    df = read_quality_csv(p)
    assert df.loc[3, "Dissolved oxygen (mg/L)"] == "3.16.2"      # not coerced at load time
    assert df.loc[0, "Cadmium (mg/L)"] == ""


def test_discover_default_files_tolerates_renames(tmp_path):
    (tmp_path / "swq_chemical_parameter_x (1).csv").write_text("a")
    (tmp_path / "SWQ_Biological_parameter.CSV").write_text("a")
    (tmp_path / "HydroRIVERS_v10_as.gdb.zip").write_text("a")
    found = discover_default_files(tmp_path)
    assert found["chemical"].name.startswith("swq_chemical")
    assert found["biological"] is not None
    assert found["hydrorivers"] is not None and found["physical"] is None
