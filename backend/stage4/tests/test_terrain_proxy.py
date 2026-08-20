"""T4B.3 — terrain heightmap proxy tests.

Uses a REAL GeoTIFF written to a temp file (rasterio round-trip, not a
hand-crafted byte blob), so the windowing/decimation/alignment logic runs
against a genuine raster rather than a mock. Values are a synthetic ramp
+ hill, clearly not real Vellore terrain — the live endpoint is verified
separately against the actual registered CartoDEM.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.stage4.terrain.dem_proxy import (
    TerrainUnavailableError,
    _bbox_around,
    read_lod_pair,
)

SITE_LAT, SITE_LON = 12.969223, 79.155934


def _write_dem(path: Path, size: int = 400) -> str:
    """A real EPSG:4326 GeoTIFF at ~30m pixels, centred on the site."""
    deg = 0.00027778  # ~30m, matching CartoDEM's real pixel size
    west = SITE_LON - (size / 2) * deg
    north = SITE_LAT + (size / 2) * deg

    y, x = np.mgrid[0:size, 0:size]
    # A ramp plus a hill, so terrain genuinely curves (a flat surface would
    # hide the LOD-edge problems these tests exist to catch).
    elevation = (
        100.0
        + 0.05 * x
        + 0.03 * y
        + 30.0 * np.exp(-(((x - size / 2) ** 2 + (y - size / 2) ** 2) / (2 * 40.0**2)))
    ).astype(np.float32)

    with rasterio.open(
        path, "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:4326",
        transform=from_origin(west, north, deg, deg), nodata=np.nan,
    ) as dst:
        dst.write(elevation, 1)
    return str(path)


def _lod_pair(tmp_path: Path):
    raster = _write_dem(tmp_path / "dem.tif")
    return read_lod_pair(
        raster,
        _bbox_around(SITE_LAT, SITE_LON, 2000.0),
        _bbox_around(SITE_LAT, SITE_LON, 150.0),
        64,
    )


def test_site_lod_is_finer_than_the_regional_surround(tmp_path: Path) -> None:
    """The whole point of the split — an earlier version had it INVERTED."""
    regional, site = _lod_pair(tmp_path)
    assert site.resolution_m < regional.resolution_m
    assert regional.rows <= 64 and regional.cols <= 64


def test_shared_boundary_elevations_match_exactly(tmp_path: Path) -> None:
    """The real seam guarantee.

    Two independent bilinear windowed reads of the same raster were tried
    first and disagreed by up to 2.9m — a visible cliff in the render.
    Both LODs now come from ONE native read, so corners must agree to the
    bit, not merely approximately.
    """
    regional, site = _lod_pair(tmp_path)

    def sample(hm, lat: float, lon: float) -> float:
        r = round((hm.max_lat - lat) / (hm.max_lat - hm.min_lat) * (hm.rows - 1))
        c = round((lon - hm.min_lon) / (hm.max_lon - hm.min_lon) * (hm.cols - 1))
        value = hm.elevation_grid[max(0, min(hm.rows - 1, r))][max(0, min(hm.cols - 1, c))]
        assert value is not None
        return value

    for lat, lon in (
        (site.max_lat, site.min_lon),
        (site.max_lat, site.max_lon),
        (site.min_lat, site.min_lon),
        (site.min_lat, site.max_lon),
    ):
        assert sample(regional, lat, lon) == pytest.approx(sample(site, lat, lon), abs=1e-9)


def test_site_extent_snaps_onto_regional_sample_lines(tmp_path: Path) -> None:
    """Corners land on whole regional grid indices.

    This is what lets the frontend cut the covered regional faces without
    leaving a gap — if it were fractional, the hole would not align.
    """
    regional, site = _lod_pair(tmp_path)
    lat_span = regional.max_lat - regional.min_lat
    lon_span = regional.max_lon - regional.min_lon
    for value in (
        (regional.max_lat - site.max_lat) / lat_span * (regional.rows - 1),
        (regional.max_lat - site.min_lat) / lat_span * (regional.rows - 1),
        (site.min_lon - regional.min_lon) / lon_span * (regional.cols - 1),
        (site.max_lon - regional.min_lon) / lon_span * (regional.cols - 1),
    ):
        assert abs(value - round(value)) < 1e-6, f"{value} is not on a regional sample line"


def test_nodata_becomes_null_never_a_number(tmp_path: Path) -> None:
    """Real CartoDEM voids must stay visibly missing, not be filled in."""
    raster = tmp_path / "holey.tif"
    _write_dem(raster)
    with rasterio.open(raster, "r+") as src:
        band = src.read(1)
        # Near the raster centre so the void really falls inside the 4km
        # regional window -- a first version put it in a corner, which the
        # window never reaches (the test raster spans ~12km).
        band[170:200, 170:200] = np.nan
        src.write(band, 1)

    regional, _ = read_lod_pair(
        str(raster),
        _bbox_around(SITE_LAT, SITE_LON, 2000.0),
        _bbox_around(SITE_LAT, SITE_LON, 150.0),
        64,
    )
    flat = [v for row in regional.elevation_grid for v in row]
    assert regional.nodata_cell_count == sum(1 for v in flat if v is None)
    assert regional.nodata_cell_count > 0
    assert all(v is None or math.isfinite(v) for v in flat)


def test_unreadable_raster_raises_rather_than_returning_flat_ground(tmp_path: Path) -> None:
    with pytest.raises(TerrainUnavailableError):
        read_lod_pair(
            str(tmp_path / "does_not_exist.tif"),
            _bbox_around(SITE_LAT, SITE_LON, 2000.0),
            _bbox_around(SITE_LAT, SITE_LON, 150.0),
            64,
        )
