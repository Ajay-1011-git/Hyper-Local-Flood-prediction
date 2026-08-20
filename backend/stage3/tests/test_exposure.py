"""Tests for T3.2 — road segmentation (and T3.3's exposure scoring, added
in that task).

No real Stage 2 GLB/mesh exists (Stage 2 hasn't been built in this repo
yet), so these fixtures are synthetic geometry built directly in the
shapes `road_segmentation.py`'s module docstring documents as assumed —
explicitly labeled fixtures throughout, never presented as real Stage 2
mesh output.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from backend.stage3.exposure.road_segmentation import (
    AmbiguousRoadGeometryError,
    UnsupportedRoadMeshFormatError,
    segment_road_network,
)


@dataclass
class _FakeTrimeshLike:
    """Mimics trimesh.Trimesh's .vertices/.faces attribute interface —
    ASSUMPTION 1 in road_segmentation.py's docstring."""

    vertices: np.ndarray
    faces: np.ndarray


def _make_straight_ribbon(
    length_m: float, width_m: float, n_points_along: int, x_offset: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """A real triangulated mesh strip along the +x axis — not just a point
    cloud, so connected-component analysis via face adjacency is
    genuinely exercised."""
    xs = np.linspace(x_offset, x_offset + length_m, n_points_along)
    vertex_rows: list[list[float]] = []
    for x in xs:
        vertex_rows.append([x, -width_m / 2, 0.0])
        vertex_rows.append([x, width_m / 2, 0.0])
    vertices = np.array(vertex_rows)

    face_rows: list[list[int]] = []
    for i in range(n_points_along - 1):
        v0, v1, v2, v3 = 2 * i, 2 * i + 1, 2 * (i + 1), 2 * (i + 1) + 1
        face_rows.append([v0, v1, v2])
        face_rows.append([v1, v3, v2])
    faces = np.array(face_rows)
    return vertices, faces


def test_segments_a_single_straight_road():
    vertices, faces = _make_straight_ribbon(length_m=100.0, width_m=6.0, n_points_along=51)
    mesh = _FakeTrimeshLike(vertices=vertices, faces=faces)

    segments = segment_road_network(mesh, segment_length_m=20.0)

    # 100m / 20m -> 5 segments.
    assert len(segments) == 5
    for seg in segments:
        assert seg.width_m == pytest.approx(6.0, abs=0.5)

    # Combined extent (first point of first segment to last point of last
    # segment) roughly matches the original mesh's bounding box, per the
    # build doc's VERIFY instruction.
    all_x = [p[0] for seg in segments for p in seg.polyline]
    assert min(all_x) == pytest.approx(0.0, abs=1.0)
    assert max(all_x) == pytest.approx(100.0, abs=1.0)


def test_segment_ids_are_deterministic_and_sequential():
    vertices, faces = _make_straight_ribbon(length_m=40.0, width_m=4.0, n_points_along=21)
    mesh = _FakeTrimeshLike(vertices=vertices, faces=faces)

    segments = segment_road_network(mesh, segment_length_m=20.0)
    assert [s.segment_id for s in segments] == ["road_seg_000", "road_seg_001"]


def test_two_disconnected_roads_produce_separate_components():
    """Two separate road strips with non-overlapping vertex indices (no
    shared faces) -- connected-component analysis must split them, not
    treat them as one continuous road."""
    v1, f1 = _make_straight_ribbon(length_m=30.0, width_m=5.0, n_points_along=16, x_offset=0.0)
    v2, f2 = _make_straight_ribbon(
        length_m=30.0, width_m=5.0, n_points_along=16, x_offset=1000.0
    )
    # Offset second road's face indices past the first road's vertex count.
    f2_offset = f2 + len(v1)
    combined_vertices = np.vstack([v1, v2])
    combined_faces = np.vstack([f1, f2_offset])
    mesh = _FakeTrimeshLike(vertices=combined_vertices, faces=combined_faces)

    segments = segment_road_network(mesh, segment_length_m=30.0)

    # Each road (30m, chunked at 30m) yields exactly 1 segment -> 2 total,
    # and they must not be merged into one long "segment" spanning the
    # 1000m gap between them (which no shared face connects).
    assert len(segments) == 2
    x_starts = sorted(seg.polyline[0][0] for seg in segments)
    assert x_starts[0] == pytest.approx(0.0, abs=1.0)
    assert x_starts[1] == pytest.approx(1000.0, abs=1.0)


def test_ambiguous_blob_geometry_raises_rather_than_guessing():
    """A roughly circular/blob-shaped point cluster (an intersection, not
    a road strip) has no single dominant direction -- must raise, not
    force an arbitrary segmentation onto it."""
    rng = np.random.default_rng(7)
    angles = rng.uniform(0, 2 * np.pi, 40)
    radii = rng.uniform(0, 10, 40)
    blob = np.column_stack(
        [radii * np.cos(angles), radii * np.sin(angles), np.zeros(40)]
    )
    mesh = _FakeTrimeshLike(vertices=blob, faces=np.empty((0, 3), dtype=int))

    with pytest.raises(AmbiguousRoadGeometryError):
        segment_road_network(mesh, segment_length_m=20.0)


def test_too_few_points_raises():
    mesh = _FakeTrimeshLike(
        vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        faces=np.empty((0, 3), dtype=int),
    )
    with pytest.raises(AmbiguousRoadGeometryError):
        segment_road_network(mesh, segment_length_m=20.0)


def test_accepts_dict_shaped_input():
    vertices, faces = _make_straight_ribbon(length_m=25.0, width_m=4.0, n_points_along=13)
    mesh_dict = {"vertices": vertices.tolist(), "faces": faces.tolist()}

    segments = segment_road_network(mesh_dict, segment_length_m=20.0)
    assert len(segments) >= 1


def test_accepts_raw_array_input_without_faces():
    vertices, _ = _make_straight_ribbon(length_m=25.0, width_m=4.0, n_points_along=13)
    # Raw point cloud, no connectivity info -- treated as one component.
    segments = segment_road_network(vertices, segment_length_m=20.0)
    assert len(segments) >= 1


def test_unsupported_format_raises():
    with pytest.raises(UnsupportedRoadMeshFormatError):
        segment_road_network(object(), segment_length_m=20.0)

    with pytest.raises(UnsupportedRoadMeshFormatError):
        segment_road_network("not a mesh", segment_length_m=20.0)
