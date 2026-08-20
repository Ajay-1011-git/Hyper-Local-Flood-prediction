"""Tests for DEM interpolation and footprint extraction (T2.2/T2.3, amended
2026-08-20 for the real SiteTransform-based georeferencing)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from stage2.terrain.dem_interpolation import (
    compute_site_bbox_latlon,
    interpolate_terrain,
)
from stage2.terrain.errors import Stage1BTerrainUnavailableError
from stage2.tests.conftest import requires_postgres
from stage2.tests.fixtures import synthetic_site_transform, write_synthetic_terrain_geotiff

SITE_TRANSFORM = synthetic_site_transform()


def _building(extents: list[float]) -> dict[str, trimesh.Trimesh]:
    return {"Building_01": trimesh.creation.box(extents=extents)}


# --------------------------------------------------------- axis mapping


def test_bbox_grows_around_reference_point_with_object_extent() -> None:
    """A box centered at the scene origin (which maps to `ref_lat`/`ref_lon`)
    should straddle the reference point on both lat and lon."""
    objects = _building([2.0, 2.0, 2.0])  # centered at origin, extends +/-1 on each axis
    min_lat, max_lat, min_lon, max_lon = compute_site_bbox_latlon(objects, SITE_TRANSFORM)
    assert max_lat > SITE_TRANSFORM.ref_lat > min_lat
    assert max_lon > SITE_TRANSFORM.ref_lon > min_lon


def test_bbox_area_scales_with_object_extent() -> None:
    small_objects = _building([2.0, 2.0, 2.0])
    large_objects = _building([20.0, 2.0, 20.0])

    small_bbox = compute_site_bbox_latlon(small_objects, SITE_TRANSFORM)
    large_bbox = compute_site_bbox_latlon(large_objects, SITE_TRANSFORM)

    small_span = small_bbox[1] - small_bbox[0]
    large_span = large_bbox[1] - large_bbox[0]
    assert large_span == pytest.approx(small_span * 10.0, rel=1e-6)


def test_bbox_is_ground_plane_only_height_ignored() -> None:
    """glTF Y-up: only (X, Z) determine the footprint bbox -- a taller box
    with the same footprint must give the identical bbox."""
    short = _building([4.0, 2.0, 4.0])
    tall = _building([4.0, 200.0, 4.0])
    assert compute_site_bbox_latlon(short, SITE_TRANSFORM) == compute_site_bbox_latlon(
        tall, SITE_TRANSFORM
    )


# ------------------------------------------------------ terrain interpolation


def test_interpolate_terrain_produces_real_elevation_values(tmp_path: Path) -> None:
    geotiff_path = tmp_path / "terrain.tif"
    write_synthetic_terrain_geotiff(geotiff_path)

    # bbox roughly inside the synthetic raster's real coverage
    import rasterio
    from rasterio.warp import transform as warp_transform

    with rasterio.open(geotiff_path) as src:
        xs = [src.bounds.left + 20, src.bounds.right - 20]
        ys = [src.bounds.bottom + 20, src.bounds.top - 20]
        lons, lats = warp_transform(src.crs, "EPSG:4326", xs, ys)
    bbox = (min(lats), max(lats), min(lons), max(lons))

    grid = interpolate_terrain(geotiff_path, "test-site", bbox, resolution_m=2.0)

    assert grid.interpolated_from_regional_dem is True
    values = np.array(grid.elevation_grid)
    assert values.size > 0
    finite = values[np.isfinite(values)]
    assert finite.size > 0
    assert 150.0 < finite.mean() < 250.0  # matches the synthetic fixture's ~200m baseline


def test_interpolate_terrain_resolution_changes_grid_shape(tmp_path: Path) -> None:
    geotiff_path = tmp_path / "terrain.tif"
    write_synthetic_terrain_geotiff(geotiff_path)

    import rasterio
    from rasterio.warp import transform as warp_transform

    with rasterio.open(geotiff_path) as src:
        xs = [src.bounds.left + 10, src.bounds.right - 10]
        ys = [src.bounds.bottom + 10, src.bounds.top - 10]
        lons, lats = warp_transform(src.crs, "EPSG:4326", xs, ys)
    bbox = (min(lats), max(lats), min(lons), max(lons))

    coarse = interpolate_terrain(geotiff_path, "s", bbox, resolution_m=10.0)
    fine = interpolate_terrain(geotiff_path, "s", bbox, resolution_m=1.0)

    coarse_cells = len(coarse.elevation_grid) * len(coarse.elevation_grid[0])
    fine_cells = len(fine.elevation_grid) * len(fine.elevation_grid[0])
    assert fine_cells > coarse_cells


# ------------------------------------------------------- Stage 1B DB lookup


@requires_postgres
@pytest.mark.asyncio
async def test_find_terrain_grid_path_real_db_round_trip() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from stage2.config import get_settings
    from stage2.terrain.dem_source import (
        _metadata,
        _to_asyncpg_url,
        find_terrain_grid_path,
    )

    settings = get_settings()
    engine = create_async_engine(_to_asyncpg_url(settings.stage1b_database_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)
            await conn.execute(
                text(
                    "INSERT INTO dem_metadata "
                    "(min_lat, max_lat, min_lon, max_lon, terrain_grid_path) "
                    "VALUES (:min_lat, :max_lat, :min_lon, :max_lon, :path) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "min_lat": 12.0,
                    "max_lat": 13.5,
                    "min_lon": 78.5,
                    "max_lon": 80.0,
                    "path": "/fake/path/terrain.tif",
                },
            )

        path = await find_terrain_grid_path(12.9165, 79.1325, settings)
        assert path == "/fake/path/terrain.tif"

        with pytest.raises(Stage1BTerrainUnavailableError):
            await find_terrain_grid_path(0.0, 0.0, settings)  # nowhere near the test row
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM dem_metadata WHERE terrain_grid_path = '/fake/path/terrain.tif'"))
        await engine.dispose()


# ------------------------------------------------------- footprint extraction


def test_extracts_plausible_footprint_and_height() -> None:
    from stage2.terrain.footprint_extraction import extract_building_footprints

    buildings = {"Building_01": trimesh.creation.box(extents=[8.0, 12.0, 6.0])}  # Y-up: 12=height
    footprints = extract_building_footprints(buildings, SITE_TRANSFORM)

    assert len(footprints) == 1
    fp = footprints[0]
    assert fp.building_id == "Building_01"
    assert fp.height_m == pytest.approx(12.0)
    # area of an 8x6 (X x Z) box's footprint should be close to 48 m^2
    from shapely.geometry import Polygon

    area = Polygon(fp.footprint_polygon).area
    assert area == pytest.approx(48.0, rel=1e-6)


def test_footprint_area_sane_relative_to_raw_bounding_box() -> None:
    """Sanity-check against the raw mesh bounding box, per the doc's own VERIFY ask."""
    from shapely.geometry import Polygon

    from stage2.terrain.footprint_extraction import extract_building_footprints

    mesh = trimesh.creation.box(extents=[10.0, 9.0, 10.0])
    footprints = extract_building_footprints({"Building_02": mesh}, SITE_TRANSFORM)
    area = Polygon(footprints[0].footprint_polygon).area
    bbox_area = 10.0 * 10.0
    assert 0.0 < area <= bbox_area * 1.0001  # convex hull of a box == its bbox footprint


def test_multiple_buildings_each_get_their_own_footprint() -> None:
    from stage2.terrain.footprint_extraction import extract_building_footprints

    buildings = {
        "Building_01": trimesh.creation.box(extents=[8.0, 12.0, 6.0]),
        "Building_02": trimesh.creation.box(extents=[10.0, 9.0, 10.0]),
    }
    footprints = extract_building_footprints(buildings, SITE_TRANSFORM)
    assert {fp.building_id for fp in footprints} == set(buildings.keys())
    heights = {fp.building_id: fp.height_m for fp in footprints}
    assert heights["Building_01"] == pytest.approx(12.0)
    assert heights["Building_02"] == pytest.approx(9.0)


def test_disconnected_mesh_pieces_are_merged_not_ambiguous() -> None:
    """Real-data correction: multi-piece buildings are normal (see
    footprint_extraction.py's module docstring) -- T2.1 already merges
    same-prefix fragments before T2.3 ever sees them, so a disconnected
    mesh here should just produce one combined footprint, not an error."""
    from stage2.terrain.footprint_extraction import extract_building_footprints

    piece_a = trimesh.creation.box(extents=[1, 1, 1]).apply_translation([0, 0, 0])
    piece_b = trimesh.creation.box(extents=[1, 1, 1]).apply_translation([20, 0, 20])
    disconnected = trimesh.util.concatenate([piece_a, piece_b])
    assert isinstance(disconnected, trimesh.Trimesh)

    footprints = extract_building_footprints({"Building_01": disconnected}, SITE_TRANSFORM)
    assert len(footprints) == 1
    assert footprints[0].building_id == "Building_01"


def test_degenerate_geometry_raises_ambiguous_geometry_error() -> None:
    from stage2.terrain.errors import AmbiguousGeometryError
    from stage2.terrain.footprint_extraction import extract_building_footprints

    # All vertices collinear -- convex hull degenerates to a line, not a Polygon.
    line = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [2, 0, 0]], faces=[])
    with pytest.raises(AmbiguousGeometryError):
        extract_building_footprints({"Building_01": line}, SITE_TRANSFORM)


def test_scale_factor_affects_footprint_and_height() -> None:
    from shapely.geometry import Polygon

    from stage2.terrain.footprint_extraction import extract_building_footprints

    mesh = trimesh.creation.box(extents=[8.0, 12.0, 6.0])
    unit_scale = extract_building_footprints({"Building_01": mesh}, SITE_TRANSFORM)[0]

    import dataclasses

    doubled_transform = dataclasses.replace(SITE_TRANSFORM, scale=2.0)
    double_scale = extract_building_footprints({"Building_01": mesh}, doubled_transform)[0]

    assert unit_scale.height_m is not None and double_scale.height_m is not None
    assert double_scale.height_m == pytest.approx(unit_scale.height_m * 2.0)
    unit_area = Polygon(unit_scale.footprint_polygon).area
    double_area = Polygon(double_scale.footprint_polygon).area
    assert double_area == pytest.approx(unit_area * 4.0)  # area scales with the square
