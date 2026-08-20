"""Tests for computational mesh assembly (T2.4, amended 2026-08-20 for
SiteTransform-based georeferencing and raised-terrain features)."""

from __future__ import annotations

import math

import pytest

from stage2.mesh.computational_mesh import build_computational_mesh
from stage2.mesh.errors import DoubleTaggedNodeError
from stage2.shared.contracts import BuildingFootprint, RoadSegment, TerrainGrid
from stage2.tests.fixtures import synthetic_site_transform

SITE_TRANSFORM = synthetic_site_transform()


def _flat_terrain(size: int = 5, resolution_m: float = 2.0) -> TerrainGrid:
    return TerrainGrid(
        site_id="test-site",
        resolution_m=resolution_m,
        origin_lat=SITE_TRANSFORM.ref_lat,
        origin_lon=SITE_TRANSFORM.ref_lon,
        elevation_grid=[[216.0 + r + c for c in range(size)] for r in range(size)],
        interpolated_from_regional_dem=True,
    )


def test_node_count_matches_grid_cells() -> None:
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], SITE_TRANSFORM)
    assert len(nodes) == 25


def test_4_connectivity_edge_count() -> None:
    """A 5x5 grid has 2*5*4=40 internal edges under 4-connectivity."""
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], SITE_TRANSFORM)
    assert len(edges) == 40


def test_no_wall_nodes_without_footprints() -> None:
    terrain = _flat_terrain(size=5)
    nodes, edges = build_computational_mesh(terrain, [], SITE_TRANSFORM)
    assert all(not n.is_wall_node for n in nodes)


def _centered_terrain(size: int, resolution_m: float) -> TerrainGrid:
    """A terrain grid whose origin (top-left/north-west corner) is offset
    from the reference point so the grid spans both sides of it (west/east,
    north/south) -- matching how a real T2.2-computed grid's origin sits at
    the site bbox's corner, not at the reference point itself."""
    half_span_m = (size * resolution_m) / 2.0
    half_span_deg_lat = half_span_m / 111_320.0
    half_span_deg_lon = half_span_m / (
        111_320.0 * math.cos(math.radians(SITE_TRANSFORM.ref_lat))
    )
    return TerrainGrid(
        site_id="test-site",
        resolution_m=resolution_m,
        origin_lat=SITE_TRANSFORM.ref_lat + half_span_deg_lat,
        origin_lon=SITE_TRANSFORM.ref_lon - half_span_deg_lon,
        elevation_grid=[[216.0] * size for _ in range(size)],
        interpolated_from_regional_dem=True,
    )


def test_wall_nodes_tagged_correctly_and_count_matches_footprint_area() -> None:
    terrain = _centered_terrain(size=11, resolution_m=1.0)  # covers -5m..+5m each axis
    # A 4x4m footprint centered at the origin
    footprint = BuildingFootprint(
        building_id="Building_01",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=10.0,
    )
    nodes, edges = build_computational_mesh(terrain, [footprint], SITE_TRANSFORM)
    wall_nodes = [n for n in nodes if n.is_wall_node]
    assert len(wall_nodes) > 0
    assert all(n.building_id == "Building_01" for n in wall_nodes)
    # sanity: wall node count should roughly match footprint area / cell area
    # (4m x 4m = 16 m^2 at 1m resolution ~ 16 cells, generous tolerance for
    # discretization at the polygon boundary)
    assert 9 <= len(wall_nodes) <= 25


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
    nodes, edges = build_computational_mesh(terrain, footprints, SITE_TRANSFORM)
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
        build_computational_mesh(terrain, overlapping, SITE_TRANSFORM)


def test_edge_slope_reflects_real_elevation_difference() -> None:
    terrain = TerrainGrid(
        site_id="test-site",
        resolution_m=1.0,
        origin_lat=SITE_TRANSFORM.ref_lat,
        origin_lon=SITE_TRANSFORM.ref_lon,
        elevation_grid=[[100.0, 105.0], [100.0, 100.0]],
        interpolated_from_regional_dem=True,
    )
    nodes, edges = build_computational_mesh(terrain, [], SITE_TRANSFORM)
    horizontal_edge = next(
        e for e in edges if e.node_id_a == "n_0_0" and e.node_id_b == "n_0_1"
    )
    assert horizontal_edge.slope == pytest.approx(5.0 / horizontal_edge.distance_m)
    assert horizontal_edge.distance_m > 0


# ------------------------------------------------------- raised terrain features


def test_raised_terrain_feature_offsets_elevation_not_wall() -> None:
    """The circular garden bed (Garden_Bed_Ring) is raised terrain, NOT an
    obstacle: confirmed with the project owner 2026-08-20 -- water should
    only cross it once flood depth exceeds its raise height. A cell inside
    the raised footprint must get an elevation offset and must NOT be
    tagged `is_wall_node`."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    garden = BuildingFootprint(
        building_id="Garden_Bed_Ring",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=0.5,
    )
    nodes, edges = build_computational_mesh(
        terrain, [], SITE_TRANSFORM, raised_terrain_features=[(garden, 0.5)]
    )
    center_node = next(n for n in nodes if n.node_id == "n_5_5")  # centered grid's middle cell
    outside_node = next(n for n in nodes if n.node_id == "n_0_0")

    assert center_node.elevation_m == pytest.approx(216.0 + 0.5)
    assert outside_node.elevation_m == pytest.approx(216.0)
    assert center_node.is_wall_node is False
    assert center_node.building_id is None


def test_raised_terrain_feature_propagates_into_edge_slope() -> None:
    """Raised terrain must affect the flow-physics edges too (via node
    elevation), not just the node's own elevation_m field."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    garden = BuildingFootprint(
        building_id="Garden_Bed_Ring",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=1.0,
    )
    nodes, edges = build_computational_mesh(
        terrain, [], SITE_TRANSFORM, raised_terrain_features=[(garden, 1.0)]
    )
    # n_5_7 (east~1.5m, inside the raised footprint) -> n_5_8 (east~2.5m,
    # just outside it): this edge straddles the raise boundary, so it must
    # show a nonzero slope even though the underlying flat DEM does not.
    edge = next(
        e
        for e in edges
        if {e.node_id_a, e.node_id_b} == {"n_5_7", "n_5_8"}
    )
    assert abs(edge.slope) > 0.0


def test_raised_and_wall_can_coexist_orthogonally() -> None:
    """A cell can be inside a raised feature's footprint while a separate
    building footprint elsewhere tags other cells as walls -- the two
    mechanisms don't interfere with each other."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    garden = BuildingFootprint(
        building_id="Garden_Bed_Ring",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=0.5,
    )
    building = BuildingFootprint(
        building_id="Building_01",
        footprint_polygon=[[3.0, 3.0], [3.0, 4.0], [4.0, 4.0], [4.0, 3.0], [3.0, 3.0]],
        height_m=10.0,
    )
    nodes, edges = build_computational_mesh(
        terrain, [building], SITE_TRANSFORM, raised_terrain_features=[(garden, 0.5)]
    )
    garden_node = next(n for n in nodes if n.node_id == "n_5_5")
    wall_nodes = [n for n in nodes if n.is_wall_node]

    assert garden_node.elevation_m == pytest.approx(216.5)
    assert garden_node.is_wall_node is False
    assert len(wall_nodes) > 0
    assert all(n.elevation_m == pytest.approx(216.0) for n in wall_nodes)


# --------------------------------------------------------------- road tagging
# (2026-08-20 addition — see terrain/road_segmentation.py's module docstring
# for why this exists: Stage 3's rank_structures needs road_segment_id on
# NodeState, and this is the only place that link can be made.)


def test_cells_near_a_road_segment_get_tagged() -> None:
    terrain = _centered_terrain(size=11, resolution_m=1.0)  # -5m..+5m each axis
    # A straight road segment along the east axis, through the origin.
    road = RoadSegment(segment_id="Road_Segment_000", polyline=[[-5.0, 0.0], [5.0, 0.0]])
    nodes, edges = build_computational_mesh(
        terrain, [], SITE_TRANSFORM, road_segments=[road], road_tagging_buffer_m=1.0
    )
    on_road = next(n for n in nodes if n.node_id == "n_5_5")  # centered cell, on the road
    off_road = next(n for n in nodes if n.node_id == "n_0_0")  # far corner

    assert on_road.road_segment_id == "Road_Segment_000"
    assert off_road.road_segment_id is None


def test_road_tagging_respects_the_buffer_distance() -> None:
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    road = RoadSegment(segment_id="Road_Segment_000", polyline=[[-5.0, 0.0], [5.0, 0.0]])
    nodes, edges = build_computational_mesh(
        terrain, [], SITE_TRANSFORM, road_segments=[road], road_tagging_buffer_m=0.5
    )
    # n_3_5 sits at north~=2m (row 3 of 11, centered) -- well outside a 0.5m buffer.
    far_from_road = next(n for n in nodes if n.node_id == "n_3_5")
    assert far_from_road.road_segment_id is None


def test_wall_nodes_are_never_also_tagged_as_road_nodes() -> None:
    """A building interior cell must not also carry a road_segment_id,
    even if a road segment happens to pass geometrically near/through the
    building's footprint (roads and buildings don't overlap in this
    site's real geometry, but the tagging logic itself must not assume
    that -- it must actively exclude wall cells)."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    building = BuildingFootprint(
        building_id="Building_01",
        footprint_polygon=[[-2.0, -2.0], [-2.0, 2.0], [2.0, 2.0], [2.0, -2.0], [-2.0, -2.0]],
        height_m=10.0,
    )
    road = RoadSegment(segment_id="Road_Segment_000", polyline=[[-5.0, 0.0], [5.0, 0.0]])
    nodes, edges = build_computational_mesh(
        terrain, [building], SITE_TRANSFORM, road_segments=[road], road_tagging_buffer_m=3.0
    )
    wall_nodes = [n for n in nodes if n.is_wall_node]
    assert len(wall_nodes) > 0
    assert all(n.road_segment_id is None for n in wall_nodes)


def test_no_road_segments_tags_nothing() -> None:
    """The default (no road_segments given) must never fabricate a tag."""
    terrain = _centered_terrain(size=11, resolution_m=1.0)
    nodes, edges = build_computational_mesh(terrain, [], SITE_TRANSFORM)
    assert all(n.road_segment_id is None for n in nodes)
