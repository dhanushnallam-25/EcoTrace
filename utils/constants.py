"""
Static domain knowledge: canonical column names, parameter catalogue, CPCB screening
criteria, plausibility (physical-possibility) limits and station-type keywords.

All thresholds here are *defaults* and can be overridden from the UI.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- metadata columns
# canonical_name -> list of accepted raw header spellings (compared case/space-insensitively)
METADATA_ALIASES = {
    "slno": ["SlNo", "Sl No", "S.No", "Serial No", "Sl. No."],
    "station": ["Station", "Station Name", "Monitoring Station", "Location"],
    "agency": ["Agency"],
    "state": ["State"],
    "state_lgd": ["State LGD Code"],
    "district": ["District"],
    "district_lgd": ["District LGD Code"],
    "tehsil": ["Tehsil", "Taluk"],
    "block": ["Block"],
    "village": ["Village"],
    "river": ["River", "River Name"],
    "basin": ["Basin"],
    "tributary": ["Tributary"],
    "subtributary": ["Subtributary", "Sub Tributary"],
    "subsubtributary": ["SubSubtributary"],
    "local_river": ["Local River"],
    "lat": ["Latitude", "Lat"],
    "lon": ["Longitude", "Lon", "Long"],
    "timestamp": ["Data Acquisition Time", "Date", "Sampling Date", "Date Time", "Timestamp"],
}
REQUIRED_METADATA = ["station", "lat", "lon", "timestamp"]
DEDUP_KEY = ["station", "timestamp", "lat", "lon"]

# --------------------------------------------------------------------------- parameters
# Core parameters EcoTrace analyses. Other numeric columns are kept with a slugified key.
PARAMETERS = {
    "ph": {"label": "pH", "unit": "", "aliases": ["Potential of Hydrogen (pH)", "pH"]},
    "do": {"label": "Dissolved Oxygen", "unit": "mg/L", "aliases": ["Dissolved oxygen (mg/L)", "DO (mg/L)", "DO"]},
    "bod": {"label": "BOD", "unit": "mg/L", "aliases": ["Biochemical Oxygen Demand (mg/L)", "BOD (mg/L)", "BOD"]},
    "cod": {"label": "COD", "unit": "mg/L", "aliases": ["Chemical Oxygen Demand (mg/L)", "COD (mg/L)", "COD"]},
    "ammonia_n": {"label": "Ammonia-N", "unit": "mgN/L", "aliases": ["Amonia N (mgN/L)", "Ammonia N (mgN/L)", "Ammonia N"]},
    "total_coliform": {"label": "Total Coliform", "unit": "MPN/100mL",
                       "aliases": ["Total Coliform (MPN/100mL)", "Total Coliform"]},
    "fecal_coliform": {"label": "Fecal Coliform", "unit": "MPN/100mL",
                       "aliases": ["Fecal Coliform (MPN/100mL)", "Faecal Coliform (MPN/100mL)", "Fecal Coliform"]},
    "conductivity": {"label": "Conductivity", "unit": "µS/cm", "aliases": ["Conductivity (µmho/cm)", "Electrical Conductivity",
                                                                          "Conductivity (umhos/cm)", "EC (µS/cm)"]},
    "temperature": {"label": "Temperature", "unit": "°C", "aliases": ["Temperature (°C)", "Water Temperature", "Temperature"]},
    "turbidity": {"label": "Turbidity", "unit": "NTU", "aliases": ["Turbidity (NTU)", "Turbidity"]},
}

# Parameters the analysis pages offer (in display order).
ANALYSIS_PARAMETERS = ["ph", "do", "bod", "ammonia_n", "total_coliform", "fecal_coliform"]

# Coliform counts span orders of magnitude -> analysed on a log10 scale.
LOG_SCALE_PARAMETERS = {"total_coliform", "fecal_coliform"}

# Direction in which a value becomes "worse" (used for direction-aware anomalies).
BAD_DIRECTION = {"ph": "both", "do": "low", "bod": "high", "ammonia_n": "high",
                 "total_coliform": "high", "fecal_coliform": "high", "cod": "high"}

# --------------------------------------------------------------------------- CPCB criteria
# Defaults are taken from CPCB "Designated Best Use" (DBU) primary water-quality criteria.
#   Class B (outdoor bathing): pH 6.5-8.5, DO >= 5 mg/L, BOD <= 3 mg/L,
#                              FC <= 500 desirable / 2500 max permissible MPN/100 mL
#   Class C (drinking source after conventional treatment): TC <= 5000 MPN/100 mL
#   Class D (wildlife & fisheries): free ammonia (as N) <= 1.2 mg/L
# Ammonia: the dataset reports total Ammonia-N, not free (un-ionised) ammonia, so the
# Class D figure is used only as a screening proxy (documented limitation).
DEFAULT_THRESHOLDS = {
    "ph": {"type": "range", "min": 6.5, "max": 8.5, "full_severity_delta": 1.5,
           "basis": "CPCB DBU Class B/D: pH 6.5–8.5"},
    "do": {"type": "min", "min": 5.0,
           "basis": "CPCB DBU Class B: DO ≥ 5 mg/L"},
    "bod": {"type": "max", "max": 3.0, "full_severity_ratio": 5.0,
            "basis": "CPCB DBU Class B/C: BOD ≤ 3 mg/L"},
    "ammonia_n": {"type": "max", "max": 1.2, "full_severity_ratio": 5.0,
                  "basis": "CPCB DBU Class D: free NH3-N ≤ 1.2 mg/L (screening proxy)"},
    "total_coliform": {"type": "max", "max": 5000.0, "full_severity_ratio": 1000.0,
                       "basis": "CPCB DBU Class C: Total Coliform ≤ 5000 MPN/100 mL"},
    "fecal_coliform": {"type": "max", "max": 2500.0, "full_severity_ratio": 1000.0,
                       "basis": "CPCB bathing criteria: Fecal Coliform ≤ 2500 MPN/100 mL (max permissible)"},
}

# --------------------------------------------------------------------------- plausibility
# Values outside these bounds are physically impossible -> quarantined (set NaN, logged).
PLAUSIBILITY_LIMITS = {
    "ph": (0.0, 14.0),
    "do": (0.0, None),
    "bod": (0.0, None),
    "cod": (0.0, None),
    "ammonia_n": (0.0, None),
    "total_coliform": (0.0, None),
    "fecal_coliform": (0.0, None),
}
# Any other concentration-type parameter must also be non-negative.
DEFAULT_NON_NEGATIVE = True

# --------------------------------------------------------------------------- station typing
# Order matters: the first matching group wins. Matching is on whole words of the name.
LAKE_KEYWORDS = ["LAKE", "KERE", "TANK", "POND", "KATTE", "KUNTE", "KALYANI", "HONDA", "SARAOVARA", "SAROVAR"]
RIVER_KEYWORDS = ["RIVER", "NALLA", "NALA", "NALAH", "DAM", "BRIDGE", "ANICUT", "BARRAGE", "RESERVOIR",
                  "CANAL", "D/S", "U/S", "DOWNSTREAM", "UPSTREAM", "STREAM", "VALLEY", "CREEK", "ESTUARY",
                  "CONFLUENCE", "SAGAR", "WEIR", "HOLE", "HALLA", "HALLI HALLA"]

STATION_TYPES = ("river", "lake", "unknown")

# HydroRIVERS attributes EcoTrace needs.
HYDRORIVERS_FIELDS = ["HYRIV_ID", "NEXT_DOWN", "MAIN_RIV", "LENGTH_KM", "DIST_DN_KM", "DIST_UP_KM",
                      "UPLAND_SKM", "DIS_AV_CMS", "ORD_STRA", "ORD_CLAS", "ORD_FLOW", "HYBAS_L12", "ENDORHEIC"]

INCIDENT_STATUSES = ["Pending", "Investigating", "Resolved"]
