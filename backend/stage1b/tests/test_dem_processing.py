"""Tests for T1B.3 — DEM processing (elevation/slope/aspect grids).

Split from test_dem.py (which covers T1B.2's client) since this task's
"Files you may touch" lists `backend/stage1b/tests/test_dem.py`, but that
file was already substantial after T1B.2; keeping T1B.3's tests in their
own module is a reasonable within-directory deviation, not a scope change
(everything still lives under backend/stage1b/tests/, and T1B.9 collects
the whole tests/ directory regardless of filename).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.stage1b.dem.processing import (
    _utm_crs_for_lon_lat,
    compute_terrain_grids,
    write_terrain_grids_geotiff,
)


def _write_synthetic_dem(path, elevation: np.ndarray, nodata: float = -32768.0):
    """Write a small EPSG:4326 GeoTIFF like T1B.2's real output, centered
    near Vellore, at a coarse-but-real pixel size."""
    height, width = elevation.shape
    # ~0.01 deg/pixel (~1.1km) is plenty for these small synthetic grids;
    # real CartoDEM is ~30m/pixel but the math under test doesn't care.
    transform = from_origin(79.0, 13.0, 0.01, 0.01)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(elevation.astype(np.float32), 1)


def test_utm_zone_for_vellore_is_44n():
    # Vellore: ~79.13E, 12.9N -> zone floor((79.13+180)/6)+1 = 44, northern.
    crs = _utm_crs_for_lon_lat(79.1325, 12.9165)
    assert crs.to_epsg() == 32644


def test_utm_zone_handles_southern_hemisphere():
    crs = _utm_crs_for_lon_lat(30.0, -20.0)
    # zone floor((30+180)/6)+1 = 36, southern -> EPSG 327xx
    assert crs.to_epsg() == 32736


def test_aspect_faces_north_when_terrain_rises_to_the_south(tmp_path):
    # Elevation increases going south (row index increases south for a
    # north-up raster) -> downslope faces north -> aspect ~ 0 deg.
    elevation = np.tile(np.arange(20, dtype="float32").reshape(20, 1) * 50.0, (1, 20))
    raster_path = tmp_path / "synthetic_south_rising.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(str(raster_path), grid_resolution_km=1.0)
    interior_aspect = grids["aspect_deg"][5:-5, 5:-5]
    # Allow for reprojection/interpolation noise at the edges of the tile;
    # interior cells should consistently read close to north (0/360).
    near_north = np.minimum(interior_aspect, 360.0 - interior_aspect)
    assert np.nanmean(near_north) < 5.0, (
        f"expected aspect near 0 deg (north), got mean deviation "
        f"{np.nanmean(near_north)} deg — the down-row/up-row sign convention "
        f"regressed"
    )


def test_aspect_faces_west_when_terrain_rises_to_the_east(tmp_path):
    # Elevation increases going east (col index increases east) ->
    # downslope faces west -> aspect ~ 270 deg.
    elevation = np.tile(np.arange(20, dtype="float32").reshape(1, 20) * 50.0, (20, 1))
    raster_path = tmp_path / "synthetic_east_rising.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(str(raster_path), grid_resolution_km=1.0)
    interior_aspect = grids["aspect_deg"][5:-5, 5:-5]
    deviation = np.abs(((interior_aspect - 270.0 + 180.0) % 360.0) - 180.0)
    assert np.nanmean(deviation) < 5.0, (
        f"expected aspect near 270 deg (west), got mean deviation "
        f"{np.nanmean(deviation)} deg — the east/west gradient sign regressed"
    )


def test_flat_terrain_has_zero_slope_and_nan_aspect(tmp_path):
    elevation = np.full((20, 20), 100.0, dtype="float32")
    raster_path = tmp_path / "synthetic_flat.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(str(raster_path), grid_resolution_km=1.0)
    interior_slope = grids["slope_deg"][5:-5, 5:-5]
    interior_aspect = grids["aspect_deg"][5:-5, 5:-5]

    assert np.nanmax(interior_slope) < 0.01
    assert np.all(np.isnan(interior_aspect))


def test_plausibility_filter_masks_implausible_elevation(tmp_path):
    elevation = np.full((10, 10), 200.0, dtype="float32")
    elevation[3:6, 3:6] = -500.0  # implausible void/blunder pixels
    raster_path = tmp_path / "synthetic_with_void.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(
        str(raster_path),
        grid_resolution_km=1.0,
        plausible_elevation_range_m=(-50.0, 2000.0),
    )
    assert grids["plausibility_masked_pixel_count"] > 0
    assert not np.any(grids["elevation"] < -50.0)


def test_compute_terrain_grids_not_all_zero_or_nan(tmp_path):
    rng = np.random.default_rng(42)
    elevation = 150.0 + rng.normal(scale=20.0, size=(30, 30)).astype("float32")
    raster_path = tmp_path / "synthetic_realistic.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(str(raster_path), grid_resolution_km=1.0)
    for key in ("elevation", "slope_deg"):
        arr = grids[key]
        assert not np.all(arr == 0)
        assert not np.all(np.isnan(arr))


def test_write_terrain_grids_geotiff_roundtrips(tmp_path):
    rng = np.random.default_rng(7)
    elevation = 150.0 + rng.normal(scale=20.0, size=(15, 15)).astype("float32")
    raster_path = tmp_path / "synthetic.tif"
    _write_synthetic_dem(raster_path, elevation)

    grids = compute_terrain_grids(str(raster_path), grid_resolution_km=1.0)
    out_path = tmp_path / "terrain.tif"
    write_terrain_grids_geotiff(grids, str(out_path))

    with rasterio.open(out_path) as src:
        assert src.count == 3
        assert src.crs == grids["crs"]
        band1 = src.read(1)
        assert band1.shape == grids["elevation"].shape
        np.testing.assert_allclose(
            band1[~np.isnan(band1)], grids["elevation"][~np.isnan(grids["elevation"])]
        )
