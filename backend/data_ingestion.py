"""
Data ingestion: locate default files, persist uploads, read CSVs as raw strings and
read/clip/cache the HydroRIVERS network.

CSV files are read with ``dtype=str`` and ``keep_default_na=False`` so that *nothing*
is silently converted at load time — malformed strings such as "3.16.2" survive into
the cleaning stage where they are flagged and quarantined with their SlNo.
"""
from __future__ import annotations

import fnmatch
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from utils.config import DEFAULT_FILE_PATTERNS, FILES_DIR, GEO_CRS, KARNATAKA_BBOX, PROCESSED_DIR, UPLOAD_DIR
from utils.constants import HYDRORIVERS_FIELDS
from utils.helpers import files_fingerprint


# --------------------------------------------------------------------------- discovery
def discover_default_files(files_dir: Path = FILES_DIR) -> Dict[str, Optional[Path]]:
    """Find the bundled default datasets, tolerating small filename differences."""
    found: Dict[str, Optional[Path]] = {}
    entries = sorted(Path(files_dir).iterdir()) if Path(files_dir).exists() else []
    for kind, patterns in DEFAULT_FILE_PATTERNS.items():
        match = None
        for pattern in patterns:
            hits = [p for p in entries if fnmatch.fnmatch(p.name.lower(), pattern.lower())]
            if hits:
                match = hits[0]
                break
        found[kind] = match
    return found


def save_upload(uploaded_file, kind: str, upload_dir: Path = UPLOAD_DIR) -> Path:
    """Persist a Streamlit UploadedFile to data/uploads/<kind>__<name>; raw bytes untouched."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(uploaded_file.name).name.replace(" ", "_")
    target = upload_dir / f"{kind}__{safe_name}"
    with open(target, "wb") as fh:
        fh.write(uploaded_file.getbuffer())
    return target


# --------------------------------------------------------------------------- CSV
def read_quality_csv(path: Path) -> pd.DataFrame:
    """Read a CPCB-style CSV with every cell as a raw string (no implicit NA/number parsing)."""
    last_err = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except UnicodeDecodeError as err:     # pragma: no cover - encoding fallback
            last_err = err
    raise ValueError(f"Could not decode {path}: {last_err}")


# --------------------------------------------------------------------------- HydroRIVERS
def _vsi_path(path: Path) -> tuple:
    """Return (gdal path, layer) for a .zip containing a .gdb or .shp, or a bare .gdb/.shp."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n.replace("\\", "/") for n in z.namelist()]
        gdbs = sorted({n.split(".gdb/")[0] + ".gdb" for n in names if ".gdb/" in n})
        if gdbs:
            return f"/vsizip/{path.as_posix()}/{gdbs[0]}", None
        shps = sorted(n for n in names if n.lower().endswith(".shp"))
        if shps:
            return f"/vsizip/{path.as_posix()}/{shps[0]}", None
        raise ValueError("Zip contains neither a .gdb nor a .shp river network")
    return path.as_posix(), None


def load_hydrorivers(path: Path, bbox=KARNATAKA_BBOX, cache_dir: Path = PROCESSED_DIR,
                     use_cache: bool = True):
    """Read HydroRIVERS clipped to ``bbox`` and cache the result as GeoParquet.

    The bbox filter is pushed down to GDAL (spatial index), so only reaches that
    intersect Karnataka are ever materialised — the Asia GDB is ~1.5 M reaches.
    """
    import geopandas as gpd
    import pyogrio

    cache_dir.mkdir(parents=True, exist_ok=True)
    bbox_tag = "_".join(f"{v:g}" for v in bbox).replace(".", "p").replace("-", "m")
    cache_path = cache_dir / f"hydrorivers_clip_{files_fingerprint([path])}_{bbox_tag}.parquet"
    if use_cache and cache_path.exists():
        return gpd.read_parquet(cache_path), cache_path, True

    src, layer = _vsi_path(path)
    layers = pyogrio.list_layers(src)
    if layer is None:
        line_layers = [name for name, gtype in layers if gtype and "LineString" in str(gtype)]
        layer = line_layers[0] if line_layers else layers[0][0]
    info = pyogrio.read_info(src, layer=layer)
    available = [f for f in HYDRORIVERS_FIELDS if f in list(info["fields"])]
    missing_core = {"HYRIV_ID", "NEXT_DOWN"} - set(available)
    if missing_core:
        raise ValueError(f"River network lacks required topology fields: {sorted(missing_core)}")

    gdf = gpd.read_file(src, layer=layer, bbox=bbox, columns=available, engine="pyogrio")
    if gdf.crs is None:
        gdf = gdf.set_crs(GEO_CRS)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(GEO_CRS)
    # MultiLineString -> keep geometry as is; shapely handles both for project/distance.
    for col in ("HYRIV_ID", "NEXT_DOWN", "MAIN_RIV"):
        if col in gdf.columns:
            gdf[col] = gdf[col].astype("int64")
    gdf = gdf.reset_index(drop=True)
    gdf.to_parquet(cache_path)
    return gdf, cache_path, False


def copy_into_uploads(path: Path, kind: str) -> Path:
    """Utility for scripts: copy an existing file into data/uploads (keeps originals intact)."""
    target = UPLOAD_DIR / f"{kind}__{Path(path).name.replace(' ', '_')}"
    if not target.exists():
        shutil.copy2(path, target)
    return target
