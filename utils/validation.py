"""Input validation helpers (uploaded files, weights, thresholds)."""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

from utils.constants import REQUIRED_METADATA


def validate_weights(weights: Dict[str, float]) -> Tuple[bool, str]:
    if any(w < 0 for w in weights.values()):
        return False, "Weights must be non-negative."
    total = sum(weights.values())
    if total <= 0:
        return False, "At least one weight must be positive."
    return True, f"Weights sum to {total:.2f} (scores are normalised by the sum)."


def validate_threshold(spec: dict) -> Tuple[bool, str]:
    kind = spec.get("type")
    if kind == "range":
        if spec.get("min") is None or spec.get("max") is None or spec["min"] >= spec["max"]:
            return False, "Range thresholds need min < max."
    elif kind == "min":
        if spec.get("min") is None:
            return False, "Minimum threshold missing."
    elif kind == "max":
        if spec.get("max") is None or spec["max"] <= 0:
            return False, "Maximum threshold must be positive."
    else:
        return False, f"Unknown threshold type: {kind}"
    return True, "ok"


def validate_required_columns(mapping: Dict[str, str]) -> List[str]:
    """Return the canonical metadata columns that could not be mapped."""
    return [c for c in REQUIRED_METADATA if c not in mapping]


def validate_river_archive(path: Path) -> Tuple[bool, str]:
    """A HydroRIVERS upload must be a zip containing a .gdb folder or a .shp file."""
    path = Path(path)
    if path.suffix.lower() == ".shp" or path.suffix.lower() == ".gdb":
        return True, "ok"
    if not zipfile.is_zipfile(path):
        return False, "River network upload must be a .zip containing a .gdb or .shp."
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    if any(".gdb/" in n.replace("\\", "/") for n in names) or any(n.lower().endswith(".shp") for n in names):
        return True, "ok"
    return False, "Zip contains neither a File Geodatabase (.gdb) nor a shapefile (.shp)."
