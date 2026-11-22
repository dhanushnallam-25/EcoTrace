"""Small, dependency-light helper functions shared across modules."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Iterable, Optional


def normalize_header(name: str) -> str:
    """Lower-case and strip everything except letters/digits so headers compare robustly."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def slugify(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", str(name))          # drop unit suffixes "(mg/L)"
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "param"


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def files_fingerprint(paths: Iterable[Optional[Path]]) -> str:
    """Cheap fingerprint from name + size + mtime (avoids hashing a 100 MB zip each rerun)."""
    h = hashlib.sha256()
    for p in paths:
        if p is None:
            h.update(b"<none>")
            continue
        p = Path(p)
        st = p.stat()
        h.update(f"{p.name}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(isinstance(value, float) and math.isnan(value))
    except TypeError:
        return False


def fmt_value(value: Any, unit: str = "", digits: int = 2) -> str:
    if is_missing(value):
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(v) >= 10000:
        text = f"{v:,.0f}"
    else:
        text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text} {unit}".strip()


def clamp01(x: float) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return max(0.0, min(1.0, float(x)))
