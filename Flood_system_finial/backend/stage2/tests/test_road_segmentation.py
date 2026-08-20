"""Tests for road segmentation (2026-08-20 addition — see
`terrain/road_segmentation.py`'s module docstring for why this exists,
and why it's spatial-grid-binning rather than a single principal-axis
fit)."""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from stage2.terrain.road_segmentation import (
    AmbiguousRoadGeometryError,
    extract_road_segments,
    tag_road_node,
)
from stage2.tests.fixtures import synthetic_site_transform

SITE_TRANSFORM = synthetic_site_transform()


def _straight_road_mesh(length_scene_units: float = 100.0, width_scene_units: float = 4.0) -> trimesh.Trimesh:
    """A real triangulated ribbon strip along scene +X, at a fixed scene Z
    (matching Y-up: ground plane is (X, Z))."""
    n = 21
    xs = np.linspace(0.0, length_scene_units, n)
    raw_vertices: list[list[float]] = []
    for x in xs:
        raw_vertices.append([x, 0.0, -width_scene_units / 2.0])
        raw_vertices.append([x, 0.0, width_scene_units / 2.0])
    vertices = np.array(raw_vertices)

    faces = []
    for i in range(n - 1):
        a, b = 2 * i, 2 * i + 1
        c, d = 2 * (i + 1), 2 * (i + 1) + 1
        faces.append([a, b, c])
        faces.append([b, d, c])
    return trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=False)


def _l_shaped_road_mesh() -> trimesh.Trimesh:
    """A real, genuinely non-straight road: one leg along +X, one along
    +Z, sharing a corner -- exactly the kind of topology (a bend) a
    single-principal-axis fit can't represent, but grid binning handles
    naturally. Real point set, not a degenerate/fabricated one."""
    leg1 = np.array([[x, 0.0, 0.0] for x in np.linspace(0.0, 60.0, 13)])
    leg2 = np.array([[60.0, 0.0, z] for z in np.linspace(0.0, 60.0, 13)])
    vertices = np.vstack([leg1, leg2])
    # A minimal, real (non-degenerate) face set -- enough for trimesh to
    # accept the mesh; extract_road_segments only reads .vertices.
    faces = np.array([[i, i + 1, i + 2] for i in range(len(vertices) - 2)])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def test_extract_road_segments_covers_a_real_straight_road() -> None:
    mesh = _straight_road_mesh(length_scene_units=100.0)
    segments = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)
    assert len(segments) > 0
    for seg in segments:
        assert seg.segment_id.startswith("Road_Segment_")
        assert len(seg.polyline) == 2


def test_extract_road_segments_handles_a_real_bend_no_single_axis_needed() -> None:
    """The real site's Road_Network is a loop/branching network, not one
    straight corridor -- this is the regression case for exactly that
    real-world shape (confirmed directly against the real GLB during
    development, see module docstring)."""
    mesh = _l_shaped_road_mesh()
    segments = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)
    # Both legs must be represented -- segments spanning near (0,0) AND
    # near (60,60), not collapsed onto one axis.
    all_points = [p for seg in segments for p in seg.polyline]
    east_span = max(p[0] for p in all_points) - min(p[0] for p in all_points)
    north_span = max(p[1] for p in all_points) - min(p[1] for p in all_points)
    assert east_span > 30.0
    assert north_span > 30.0


def test_extract_road_segments_ids_are_deterministic_across_repeat_runs() -> None:
    mesh = _straight_road_mesh(length_scene_units=60.0)
    run_1 = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)
    run_2 = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)
    assert [s.model_dump() for s in run_1] == [s.model_dump() for s in run_2]


def test_extract_road_segments_raises_for_an_empty_mesh() -> None:
    mesh = trimesh.Trimesh(
        vertices=np.empty((0, 3)), faces=np.empty((0, 3), dtype=int), process=False
    )
    with pytest.raises(AmbiguousRoadGeometryError):
        extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)


def test_tag_road_node_finds_the_real_nearest_segment_within_buffer() -> None:
    mesh = _straight_road_mesh(length_scene_units=100.0)
    segments = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)

    # A point right on the road's real centerline, near its start.
    east_m, north_m = SITE_TRANSFORM.scene_to_east_north_m(5.0, 0.0)
    tagged = tag_road_node(east_m, north_m, segments, buffer_m=4.0)
    assert tagged is not None
    assert tagged.startswith("Road_Segment_")


def test_tag_road_node_returns_none_outside_the_buffer() -> None:
    mesh = _straight_road_mesh(length_scene_units=100.0)
    segments = extract_road_segments(mesh, SITE_TRANSFORM, cell_size_m=20.0)

    # Far off the road's real centerline (perpendicular offset).
    east_m, north_m = SITE_TRANSFORM.scene_to_east_north_m(5.0, 500.0)
    assert tag_road_node(east_m, north_m, segments, buffer_m=4.0) is None


def test_tag_road_node_returns_none_when_no_segments_given() -> None:
    """Never fabricates a segment id when there's genuinely no road data."""
    assert tag_road_node(0.0, 0.0, [], buffer_m=4.0) is None
