import h3
import pytest

from core import h3compat


def test_installed_h3_is_v4_and_old_api_is_gone():
    # Documents the v1 bug: the code called geo_to_h3/k_ring/h3_to_geo, which v4 removed.
    assert h3compat.HAS_H3
    if h3compat.H3_MAJOR >= 4:
        assert not hasattr(h3, "geo_to_h3")


def test_roundtrip_res7():
    lat, lon = 18.93, 72.83
    cell = h3compat.latlng_to_cell(lat, lon, 7)
    assert len(cell) == 15
    clat, clon = h3compat.cell_to_latlng(cell)
    assert abs(clat - lat) < 0.03 and abs(clon - lon) < 0.03
    assert len(h3compat.grid_disk(cell, 1)) == 7


def test_fallback_is_deterministic(monkeypatch):
    monkeypatch.setattr(h3compat, "HAS_H3", False)
    a = h3compat.latlng_to_cell(18.93, 72.83, 7)
    assert a == h3compat.latlng_to_cell(18.93, 72.83, 7) and a.startswith("g7_")
    lat, lon = h3compat.cell_to_latlng(a)
    assert abs(lat - 18.93) < 0.1 and abs(lon - 72.83) < 0.1
    assert h3compat.grid_disk(a, 2) == [a]


def test_preprocessor_uses_compat():
    from layer3.preprocessor import GeospatialPreprocessor
    p = GeospatialPreprocessor()
    cell = p.lat_lon_to_h3(28.61, 77.21)
    assert not cell.startswith("grid_"), "real H3 expected when the wheel is installed"
    assert p.h3_to_lat_lon(cell)[0] == pytest.approx(28.61, abs=0.03)
    assert cell in p.h3_neighbors(cell, 1)
