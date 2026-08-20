"""Tests for T4B.5 support — computational-mesh node position proxy.

Same real-GeoTIFF-round-trip philosophy as `test_terrain_proxy.py` (a
synthetic EPSG:4326 raster, not a hand-crafted array), and the same
gitignored-real-data handling as `test_site_mesh.py` (the placeholder-free
paths are `skipif` the real files aren't present in this checkout).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.stage4.scene import mesh_nodes

SITE_LAT, SITE_LON = 12.969223, 79.155934


def _write_epsg4326_dem(path: Path, size: int = 300) -> str:
    """A real EPSG:4326 GeoTIFF at ~30m pixels — same convention as
    `test_terrain_proxy.py`'s own fixture, reused here rather than
    reinvented."""
    deg = 0.00027778
    west = SITE_LON - (size / 2) * deg
    north = SITE_LAT + (size / 2) * deg
    elevation = (100.0 + np.random.default_rng(0).normal(0, 2, (size, size))).astype(np.float32)
    with rasterio.open(
        path, "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:4326",
        transform=from_origin(west, north, deg, deg), nodata=np.nan,
    ) as dst:
        dst.write(elevation, 1)
    return str(path)


def _write_projected_dem(path: Path, size: int = 300) -> str:
    """A real GeoTIFF in a PROJECTED CRS (metres) — the case Stage 2's own
    `interpolate_terrain` assumes, and this module's `_terrain_grid_for_mesh`
    deliberately refuses (see its own docstring) rather than silently
    mis-sizing the grid a second way."""
    elevation = np.full((size, size), 100.0, dtype=np.float32)
    with rasterio.open(
        path, "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs="EPSG:32644",  # UTM 44N -- a real projected CRS
        transform=from_origin(500_000.0, 1_400_000.0, 1.0, 1.0), nodata=np.nan,
    ) as dst:
        dst.write(elevation, 1)
    return str(path)


@pytest.fixture(autouse=True)
def _clear_cache():
    mesh_nodes._CACHE.clear()
    yield
    mesh_nodes._CACHE.clear()


class TestTerrainGridForMesh:
    def test_sizes_the_grid_correctly_in_real_metres_not_raw_crs_units(self, tmp_path):
        """The real bug this module works around: sizing directly in a
        geographic CRS's degree units collapses a real ~130m-wide bbox to
        a 1x1 grid. At 10m resolution over a real ~130m bbox, the correct
        grid is on the order of 13x13 -- not 1x1."""
        raster = _write_epsg4326_dem(tmp_path / "dem.tif")
        bbox = (SITE_LAT - 0.0006, SITE_LAT + 0.0006, SITE_LON - 0.0007, SITE_LON + 0.0007)
        grid = mesh_nodes._terrain_grid_for_mesh(raster, bbox, resolution_m=10.0)
        rows = len(grid.elevation_grid)
        cols = len(grid.elevation_grid[0])
        assert rows > 5 and cols > 5, (
            f"got a {rows}x{cols} grid -- looks like the degrees-vs-metres bug"
        )

    def test_rejects_a_non_epsg4326_raster_rather_than_silently_mis_sizing(self, tmp_path):
        raster = _write_projected_dem(tmp_path / "dem_utm.tif")
        bbox = (SITE_LAT - 0.0006, SITE_LAT + 0.0006, SITE_LON - 0.0007, SITE_LON + 0.0007)
        with pytest.raises(mesh_nodes.MeshNodesUnavailableError):
            mesh_nodes._terrain_grid_for_mesh(raster, bbox, resolution_m=10.0)

    def test_nodata_is_filled_with_the_finite_mean_not_left_nan(self, tmp_path):
        raster = _write_epsg4326_dem(tmp_path / "dem.tif")
        bbox = (SITE_LAT - 0.0006, SITE_LAT + 0.0006, SITE_LON - 0.0007, SITE_LON + 0.0007)
        grid = mesh_nodes._terrain_grid_for_mesh(raster, bbox, resolution_m=10.0)
        flat = np.array(grid.elevation_grid)
        assert np.isfinite(flat).all()


class TestBuildSiteMeshNodes:
    async def test_raises_when_glb_missing(self, tmp_path):
        with patch.object(mesh_nodes, "_GLB_PATH", tmp_path / "no_such.glb"):
            with patch.object(mesh_nodes, "_ANCHOR_PATH", tmp_path / "no_such.json"):
                with pytest.raises(mesh_nodes.MeshNodesUnavailableError):
                    await mesh_nodes.build_site_mesh_nodes("test_site_missing")

    @pytest.mark.skipif(
        not (mesh_nodes._GLB_PATH.is_file() and mesh_nodes._ANCHOR_PATH.is_file()),
        reason="Real GLB/anchor data (gitignored) not present in this checkout.",
    )
    async def test_real_reconstruction_matches_terrain_tsx_scene_frame(self):
        result = await mesh_nodes.build_site_mesh_nodes("vit_vellore_real")

        assert result.rows * result.cols == len(result.nodes)
        node_ids = {n.node_id for n in result.nodes}
        assert "n_0_0" in node_ids
        assert f"n_{result.rows - 1}_{result.cols - 1}" in node_ids

        # Site is a few hundred metres across -- every node should be well
        # within that, in the same frame SiteMesh's real buildings land in.
        for node in result.nodes:
            assert abs(node.x_m) < 500
            assert abs(node.z_m) < 500
            assert 50.0 < node.elevation_m < 300.0  # real Vellore elevations

    @pytest.mark.skipif(
        not (mesh_nodes._GLB_PATH.is_file() and mesh_nodes._ANCHOR_PATH.is_file()),
        reason="Real GLB/anchor data (gitignored) not present in this checkout.",
    )
    async def test_result_is_cached(self):
        first = await mesh_nodes.build_site_mesh_nodes("vit_vellore_cache")
        assert "vit_vellore_cache" in mesh_nodes._CACHE
        second = await mesh_nodes.build_site_mesh_nodes("vit_vellore_cache")
        assert first is second
