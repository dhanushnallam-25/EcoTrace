"""
Shared pytest fixtures. ALL data here is SYNTHETIC (clearly labelled "SYN-...") and is
never mixed with the real CPCB files in ``files/``.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.river_graph import DirectedRiverGraph  # noqa: E402

CHEM_HEADER = ["SlNo", "Station", "Agency", "District", "River", "Latitude", "Longitude", "Data Acquisition Time",
               "Amonia N (mgN/L)", "Dissolved oxygen (mg/L)", "Potential of Hydrogen (pH)", "Cadmium (mg/L)"]
BIO_HEADER = ["SlNo", "Station", "Agency", "District", "River", "Latitude", "Longitude", "Data Acquisition Time",
              "Biochemical Oxygen Demand (mg/L)", "Chemical Oxygen Demand (mg/L)", "Fecal Coliform (MPN/100mL)",
              "Total Coliform (MPN/100mL)"]


@pytest.fixture
def chain_graph():
    """SYNTHETIC river:  A -> C, B -> C, C -> D, D -> F ; E isolated lake."""
    g = DirectedRiverGraph()
    for v in "ABCDEF":
        g.add_vertex(v, station_name=f"SYN-{v}")
    for u, v in [("A", "C"), ("B", "C"), ("C", "D"), ("D", "F")]:
        g.add_edge(u, v)
    return g


@pytest.fixture
def synthetic_chem_df():
    """SYNTHETIC chemical table that mimics the real file's quirks:
    - SYN-KERE row 4 copies the SlNo-2300 pattern: DO '3.16.2', NH3 '0.41.83', pH 78.2
    - an exact duplicate row (same station, time, lat, lon)
    - same station/time at a *different* coordinate (kept, not deduplicated)
    - a heavy-metal column that is empty (unmeasured) and blank '-' metadata
    """
    rows = [
        ["1", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-01-2021 08:30", "0.5", "6.1", "7.2", ""],
        ["2", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-02-2021 08:30", "", "5.5", "7.4", ""],
        ["3", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-02-2021 08:30", "", "5.5", "7.4", ""],
        ["4", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "09-08-2021 08:30", "0.41.83", "3.16.2", "78.2", ""],
        ["5", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "10-09-2021 08:30", "1.0", "4.0", "7.0", ""],
        ["6", "SYN-KERE", "SYN", "Synthville", "-", "12.6", "77.6", "10-09-2021 08:30", "1.1", "4.1", "7.1", ""],
        ["7", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "31-13-2021 08:30", "1.1", "4.1", "7.1", ""],
    ]
    return pd.DataFrame(rows, columns=CHEM_HEADER, dtype=str)


@pytest.fixture
def synthetic_bio_df():
    rows = [
        ["1", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-01-2021 08:30", "2", "", "", "300"],
        ["2", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-02-2021 08:30", "4", "", "900", "5.4e+06"],
        ["3", "SYN-RIVER AT POINT A", "SYN", "Synthville", "-", "12.0", "77.0", "11-02-2021 08:30", "4", "", "900", "5.4e+06"],
        ["4", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "09-08-2021 08:30", "12", "", "", ""],
        ["5", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "10-09-2021 08:30", "-1", "", "", ""],
        ["6", "SYN-KERE", "SYN", "Synthville", "-", "12.6", "77.6", "10-09-2021 08:30", "8", "", "", ""],
        ["7", "SYN-KERE", "SYN", "Synthville", "-", "12.5", "77.5", "31-13-2021 08:30", "8", "", "", ""],
    ]
    return pd.DataFrame(rows, columns=BIO_HEADER, dtype=str)
