"""Tests for computational mesh assembly (T2.4)."""

from __future__ import annotations

import pytest

from stage2.mesh.computational_mesh import build_computational_mesh
from stage2.mesh.errors import DoubleTaggedNodeError
from stage2.shared.contracts import AnchorPoint, BuildingFootprint, TerrainGrid

ANCHOR = AnchorPoint(
    scene_object_name="Anchor",
    scene_local_position=[0.0, 0.0, 0.0],
    real_world_lat=12.9165,
    real_world_lon=79.1325,
    real_world_elevation_m=216.0,
    scene_to_real_scale_factor=1.0,
    north_axis="+Y",
)


def _flat_terrain(size: int = 5, resolution_m: float = 2.0) -> TerrainGrid:
    return TerrainGrid(
        site_id="test-site",
        resolution_m=resolution_m,
        origin_lat=ANCHOR.real_world_lat,
        origin_lon=ANCHOR.real_world_lon,
        elevation_grid=[[216.0 + r + c for c in range(size)] for r in range(size)],
        interpolated_from_regional_dem=True,
    )


def test_node_count_matches_grid_cells() -> None:
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], ANCHOR)
    assert len(nodes) == 25


def test_4_connectivity_edge_count() -> None:
    """A 5x5 grid has 2*5*4=40 internal edges under 4-connectivity."""
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], ANCHOR)
    assert len(edges) == 40


def test_no_wall_nodes_without_footprints() -> None:
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], ANCHOR)
    assert all(not n.is_wall_node for n in nodes)


def test_wall_nodes_tagged_correctly_and_count_matches_footprint_area() -> None:
    terrain = _centered_terrain(size=11, resolution_m=1.0)  # covers -5m..+5m each axis
    # A 4x4m footprint centered at the origin
    footprint = BuildingFootprint(
        building_id="Building_01",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=10.0,
    )
    nodes, edges = build_computational_mesh(terrain, [footprint], ANCHOR)
    wall_nodes = [n for n in nodes if n.is_wall_node]
    assert len(wall_nodes) > 0
    assert all(n.building_id == "Building_01" for n in wall_nodes)
    # sanity: wall node count should roughly match footprint area / cell area
    # (4m x 4m = 16 m^2 at 1m resolution ~ 16 cells, generous tolerance for
    # discretization at the polygon boundary)
    assert 9 <= len(wall_nodes) <= 25


def _centered_terrain(size: int, resolution_m: float) -> TerrainGrid:
    """A terrain grid whose origin (top-left/north-west corner) is offset
    from the anchor so the grid spans both sides of it (west/east,
    north/south) -- matching how a real T2.2-computed grid's origin sits at
    the site bbox's corner, not at the anchor itself."""
    half_span_m = (size * resolution_m) / 2.0
    half_span_deg_lat = half_span_m / 111_320.0
    half_span_deg_lon = half_span_m / (
        111_320.0 * __import__("math").cos(__import__("math").radians(ANCHOR.real_world_lat))
    )
    return TerrainGrid(
        site_id="test-site",
        resolution_m=resolution_m,
        origin_lat=ANCHOR.real_world_lat + half_span_deg_lat,
        origin_lon=ANCHOR.real_world_lon - half_span_deg_lon,
        elevation_grid=[[216.0] * size for _ in range(size)],
        interpolated_from_regional_dem=True,
    )


def test_no_node_double_tagged_to_two_buildings() -> None:
    """Doc's own VERIFY ask: confirm no node is double-tagged."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    footprints = [
        BuildingFootprint(
            building_id="Building_01",
            footprint_polygon=[[-4.0, -4.0], [-4.0, -1.0], [-1.0, -1.0], [-1.0, -4.0], [-4.0, -4.0]],
            height_m=10.0,
        ),
        BuildingFootprint(
            building_id="Building_02",
            footprint_polygon=[[1.0, 1.0], [1.0, 4.0], [4.0, 4.0], [4.0, 1.0], [1.0, 1.0]],
            height_m=8.0,
        ),
    ]
    nodes, edges = build_computational_mesh(terrain, footprints, ANCHOR)
    b1_count = sum(1 for n in nodes if n.building_id == "Building_01")
    b2_count = sum(1 for n in nodes if n.building_id == "Building_02")
    assert b1_count > 0 and b2_count > 0
    # no node has both -- structurally guaranteed since building_id is a
    # single Optional[str], but confirm the counts are disjoint and sane
    wall_count = sum(1 for n in nodes if n.is_wall_node)
    assert wall_count == b1_count + b2_count


def test_overlapping_footprints_raise_typed_error() -> None:
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    overlapping = [
        BuildingFootprint(
            building_id="Building_01",
            footprint_polygon=[[-3.0, -3.0], [-3.0, 3.0], [3.0, 3.0], [3.0, -3.0], [-3.0, -3.0]],
            height_m=10.0,
        ),
        BuildingFootprint(
            building_id="Building_02",
            footprint_polygon=[[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0], [-1.0, -1.0]],
            height_m=8.0,
        ),
    ]
    with pytest.raises(DoubleTaggedNodeError):
        build_computational_mesh(terrain, overlapping, ANCHOR)


def test_edge_slope_reflects_real_elevation_difference() -> None:
    terrain = TerrainGrid(
        site_id="test-site",
        resolution_m=1.0,
        origin_lat=ANCHOR.real_world_lat,
        origin_lon=ANCHOR.real_world_lon,
        elevation_grid=[[100.0, 105.0], [100.0, 100.0]],
        interpolated_from_regional_dem=True,
    )
    nodes, edges = build_computational_mesh(terrain, [], ANCHOR)
    horizontal_edge = next(
        e for e in edges if e.node_id_a == "n_0_0" and e.node_id_b == "n_0_1"
    )
    assert horizontal_edge.slope == pytest.approx(5.0 / horizontal_edge.distance_m)
    assert horizontal_edge.distance_m > 0
