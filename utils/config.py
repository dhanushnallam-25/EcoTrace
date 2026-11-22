"""Paths and tunable pipeline configuration (all overridable from the UI)."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict

from utils.constants import DEFAULT_THRESHOLDS

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = PROJECT_ROOT / "files"
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "sample_test_data"
RESPONSE_LOG_PATH = PROCESSED_DIR / "response_log.json"

for _d in (UPLOAD_DIR, PROCESSED_DIR, SAMPLE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Default-file discovery patterns (tolerates "(1)" suffixes and similar renames).
DEFAULT_FILE_PATTERNS = {
    "chemical": ["*chemical*.csv"],
    "biological": ["*biological*.csv"],
    "physical": ["*physical*.csv"],
    "hydrorivers": ["HydroRIVERS*.zip", "*hydrorivers*.zip", "HydroRIVERS*.gdb", "HydroRIVERS*.shp"],
}

# Karnataka bounding box (lon_min, lat_min, lon_max, lat_max) used to clip HydroRIVERS Asia.
KARNATAKA_BBOX = (74.0, 11.5, 78.6, 18.5)
# UTM zone 43N — metric CRS covering most of Karnataka, used for snapping distances.
METRIC_CRS = "EPSG:32643"
GEO_CRS = "EPSG:4326"

DEFAULT_WEIGHTS = {
    "severity": 0.35,
    "persistence": 0.20,
    "downstream_reach": 0.20,
    "anomaly": 0.15,
    "data_quality": 0.10,
}


@dataclass
class PipelineConfig:
    snap_distance_km: float = 1.5            # max station -> reach snapping distance
    # A parameter is "actively monitored" if >= 10% of records carry it. In the Karnataka
    # 2021 data this keeps the 6 core parameters and treats Sodium Adsorption Ratio (6.7%,
    # a subset of stations) and the 0–0.1% heavy-metal/ion/COD columns as not monitored.
    active_param_min_coverage: float = 0.10
    high_priority_threshold: float = 60.0    # incident score >= this -> high priority
    downstream_saturation: int = 5           # reach component = min(reachable / 5, 1)
    modified_z_threshold: float = 3.5        # Iglewicz & Hoaglin outlier cut-off
    iqr_multiplier: float = 1.5              # Tukey fence
    min_obs_for_anomaly: int = 4             # need a history before calling anything anomalous
    snap_lake_stations: bool = False         # lakes stay isolated vertices by default
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    thresholds: Dict[str, dict] = field(default_factory=lambda: copy.deepcopy(DEFAULT_THRESHOLDS))

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]
