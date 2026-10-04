"""
core/h3compat.py — one API over h3 v3 and v4 (v4 renamed everything:
geo_to_h3→latlng_to_cell, k_ring→grid_disk, h3_to_geo→cell_to_latlng).
Falls back to a deterministic pseudo-index when h3 is not installed, so the
engine still runs (the caller can check HAS_H3 and report degraded mode).
"""
from __future__ import annotations

import math
from typing import List, Tuple

try:
    import h3 as _h3
    HAS_H3 = True
except Exception:  # pragma: no cover - exercised only without the wheel
    _h3 = None
    HAS_H3 = False

H3_MAJOR = int(getattr(_h3, "__version__", "0").split(".")[0]) if HAS_H3 else 0


def latlng_to_cell(lat: float, lon: float, res: int) -> str:
    if HAS_H3:
        fn = getattr(_h3, "latlng_to_cell", None) or getattr(_h3, "geo_to_h3")
        return fn(lat, lon, res)
    step = 180.0 / (2 ** (res + 3))
    return f"g{res}_{math.floor((lat + 90) / step)}_{math.floor((lon + 180) / step)}"


def grid_disk(cell: str, k: int) -> List[str]:
    if HAS_H3:
        fn = getattr(_h3, "grid_disk", None) or getattr(_h3, "k_ring")
        return list(fn(cell, k))
    return [cell]


def cell_to_latlng(cell: str) -> Tuple[float, float]:
    if HAS_H3:
        fn = getattr(_h3, "cell_to_latlng", None) or getattr(_h3, "h3_to_geo")
        lat, lon = fn(cell)
        return float(lat), float(lon)
    tag, i, j = cell.split("_")
    step = 180.0 / (2 ** (int(tag[1:]) + 3))
    return (int(i) + 0.5) * step - 90, (int(j) + 0.5) * step - 180
