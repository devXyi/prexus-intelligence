"""H3 helpers (v3/v4 API shim) — res 7 for assets/events, res 5 parents for local-area statistics."""
import h3 as _h3

_to_cell = getattr(_h3, "latlng_to_cell", None) or getattr(_h3, "geo_to_h3")
_parent = getattr(_h3, "cell_to_parent", None) or getattr(_h3, "h3_to_parent")
_disk = getattr(_h3, "grid_disk", None) or getattr(_h3, "k_ring")

EVENT_RES, AREA_RES = 7, 5


def cell(lat: float, lon: float, res: int = EVENT_RES) -> str:
    return _to_cell(lat, lon, res)


def parent(c: str, res: int = AREA_RES) -> str:
    return _parent(c, res)


def disk(c: str, k: int) -> list:
    return list(_disk(c, k))


def area_cells(c: str, k: int = 1) -> set:
    """Res-5 parent of `c` plus its k-ring: the local area used for rate statistics."""
    return set(disk(parent(c, AREA_RES), k))
