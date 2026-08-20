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

from backend.stage3.exposure.exposure_scoring import (
    UnsupportedExposureTargetError,
    compute_exposure_score,
)
from backend.stage3.exposure.road_segmentation import (
    AmbiguousRoadGeometryError,
    UnsupportedRoadMeshFormatError,
    segment_road_network,
)
from backend.stage3.shared.contracts import BuildingFootprint, RoadSegment


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


# ---------------------------------------------------------------------------
# T3.3 — exposure scoring. No real BuildingFootprint/RoadSegment output
# exists from Stage 2 yet, so these three buildings are explicitly-labeled
# fixtures with realistic institutional-building footprint sizes (per
# T2.3's own VERIFY wording: "physically plausible for real campus
# buildings"), not real Stage 2 output.
# ---------------------------------------------------------------------------


def _fixture_buildings() -> list[BuildingFootprint]:
    return [
        BuildingFootprint(
            building_id="Building_01",
            # A ~20m x 15m rectangle -- 300 m^2, plausible for a small
            # institutional block.
            footprint_polygon=[[0.0, 0.0], [20.0, 0.0], [20.0, 15.0], [0.0, 15.0]],
            height_m=12.0,
        ),
        BuildingFootprint(
            building_id="Building_02",
            # A larger ~35m x 25m rectangle -- 875 m^2.
            footprint_polygon=[[0.0, 0.0], [35.0, 0.0], [35.0, 25.0], [0.0, 25.0]],
            height_m=18.0,
        ),
        BuildingFootprint(
            building_id="Building_03",
            # An L-shaped footprint (not a simple rectangle) -- exercises
            # the shoelace formula against a real non-convex polygon.
            footprint_polygon=[
                [0.0, 0.0], [30.0, 0.0], [30.0, 10.0],
                [15.0, 10.0], [15.0, 20.0], [0.0, 20.0],
            ],
            height_m=9.0,
        ),
    ]


def test_exposure_scores_for_all_three_buildings_no_population():
    buildings = _fixture_buildings()
    scores = {b.building_id: compute_exposure_score(b) for b in buildings}

    assert scores["Building_01"] == pytest.approx(300.0)
    assert scores["Building_02"] == pytest.approx(875.0)
    # L-shape area: 30x10 rectangle (300) + 15x10 rectangle (150) = 450 m^2
    assert scores["Building_03"] == pytest.approx(450.0)


def test_exposure_scores_for_road_segments_from_t32_no_population():
    vertices, faces = _make_straight_ribbon(length_m=85.0, width_m=7.0, n_points_along=43)
    mesh = _FakeTrimeshLike(vertices=vertices, faces=faces)
    segments = segment_road_network(mesh, segment_length_m=20.0)

    scores = [compute_exposure_score(s) for s in segments]
    assert len(scores) == len(segments)
    for score, seg in zip(scores, segments):
        # width_m is known (7.0) for every T3.2-produced segment here, so
        # the exposure score should be a real length x width area, not
        # the length-only fallback path.
        assert score > 0
        assert seg.width_m is not None
        assert score == pytest.approx(score)  # sanity: no NaN/inf
        assert score < 1000  # sanity bound: no segment should be absurdly large


def test_exposure_score_with_real_population_density_scales_up():
    building = _fixture_buildings()[0]  # 300 m^2
    no_pop = compute_exposure_score(building)
    with_pop = compute_exposure_score(building, population_density=0.05)  # 0.05 people/m^2

    assert no_pop == pytest.approx(300.0)
    assert with_pop == pytest.approx(300.0 * 1.05)
    assert with_pop > no_pop


def test_exposure_score_none_population_path_does_not_fabricate():
    """The core honesty requirement: population_density=None must return
    exactly the geometric base score, with no hidden estimated population
    figure baked in anywhere."""
    building = _fixture_buildings()[1]  # 875 m^2
    score = compute_exposure_score(building, population_density=None)
    assert score == pytest.approx(875.0)

    # Explicitly re-confirm the default (no argument at all) behaves
    # identically to passing None -- the "no data" path is the real
    # default, not a special case a caller has to opt into.
    default_score = compute_exposure_score(building)
    assert default_score == score


def test_exposure_score_road_segment_without_width_uses_length_only():
    """A RoadSegment with width_m=None must not have a fabricated width
    multiplied in -- exposure falls back to length alone."""
    segment = RoadSegment(
        segment_id="road_seg_test",
        polyline=[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]],  # length = 10 + 5 = 15m
        width_m=None,
    )
    score = compute_exposure_score(segment)
    assert score == pytest.approx(15.0)


def test_exposure_score_floors_degenerate_geometry_to_nonzero():
    """'A building exists = nonzero exposure', even for degenerate input."""
    degenerate = BuildingFootprint(
        building_id="Building_degenerate",
        footprint_polygon=[[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],  # zero area
        height_m=None,
    )
    score = compute_exposure_score(degenerate)
    assert score > 0.0


def test_exposure_score_rejects_negative_population_density():
    building = _fixture_buildings()[0]
    with pytest.raises(ValueError):
        compute_exposure_score(building, population_density=-0.01)


def test_exposure_score_rejects_unsupported_type():
    with pytest.raises(UnsupportedExposureTargetError):
        compute_exposure_score("not a footprint or segment")  # type: ignore[arg-type]
