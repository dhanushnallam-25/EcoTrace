"""
Schema auto-mapping: raw CSV headers -> canonical EcoTrace column names.

Matching is alias-based on a normalised form of the header (lower-case, alphanumerics
only), so "Dissolved oxygen (mg/L)", "DISSOLVED OXYGEN(mg/l)" and "dissolved_oxygen_mgl"
all map to ``do``. Unknown numeric columns are kept as parameters under a slug key, so
an upload with extra parameters still flows through the pipeline.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from utils.constants import METADATA_ALIASES, PARAMETERS
from utils.helpers import normalize_header, slugify

_META_LOOKUP = {normalize_header(a): canon for canon, aliases in METADATA_ALIASES.items() for a in aliases + [canon]}
_PARAM_LOOKUP = {normalize_header(a): canon for canon, spec in PARAMETERS.items() for a in spec["aliases"] + [canon]}


def _unit_from_header(header: str) -> str:
    m = re.search(r"\(([^)]*)\)", header)
    return m.group(1).strip() if m else ""


def map_columns(columns: List[str], table: str = "") -> Tuple[Dict[str, str], List[dict]]:
    """Return ``(mapping raw->canonical, report rows)``.

    Report rows: raw_column, canonical, role ('metadata'|'parameter'), matched_by, label, unit, table.
    """
    mapping: Dict[str, str] = {}
    report: List[dict] = []
    used = set()
    for raw in columns:
        norm = normalize_header(raw)
        role, matched_by = "parameter", "alias"
        if norm in _META_LOOKUP:
            canon, role = _META_LOOKUP[norm], "metadata"
        elif norm in _PARAM_LOOKUP:
            canon = _PARAM_LOOKUP[norm]
        else:
            canon, matched_by = slugify(raw), "slug (unrecognised parameter)"
        base, k = canon, 2
        while canon in used:                      # never let two raw columns collide
            canon = f"{base}_{k}"
            k += 1
        used.add(canon)
        mapping[raw] = canon
        if role == "parameter":
            spec = PARAMETERS.get(canon, {})
            label = spec.get("label") or re.sub(r"\s*\(.*?\)", "", raw).strip()
            unit = spec.get("unit") if spec else _unit_from_header(raw)
        else:
            label, unit = raw, ""
        report.append({"table": table, "raw_column": raw, "canonical": canon, "role": role,
                       "matched_by": matched_by, "label": label, "unit": unit})
    return mapping, report
