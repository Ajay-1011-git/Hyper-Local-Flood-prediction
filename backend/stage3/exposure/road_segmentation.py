"""Road segmentation — T3.2.

STOP AND READ — the build doc's literal instruction couldn't be followed:
"first confirm how Stage 2 actually exposes the raw `Road_Network` mesh
data — check its real ingestion code (T2.1) rather than assuming a data
access pattern." Stage 2's T2.1 (`glb_loader.py`) does not exist in this
repo as of 2026-08-20 (Ajay hasn't started Stage 2 yet) — there is no
real code to check. Per this project's own anti-hallucination rule 4
("if a requirement is ambiguous or underspecified... state any
unavoidable assumption explicitly"), this implements against a clearly
flagged, well-justified ASSUMED shape rather than blocking:

ASSUMPTION 1 — `road_mesh_data`'s shape: Stage 2's own build doc (T2.1)
says `load_site_model()` returns "raw mesh geometry (vertices/faces)" per
object, using "trimesh or pygltflib" (its own text, undecided between
the two). `trimesh.Trimesh.vertices`/`.faces` is the standard, widely-
used convention either library's output would commonly be normalized
to, so `_extract_vertices_and_faces` below accepts that shape (an object
with `.vertices`/`.faces`, or a dict with those keys, or a raw (N,3)
array). If Stage 2's real T2.1 returns something structurally different,
this adapter function is the one place that needs updating — the
segmentation algorithm itself doesn't otherwise depend on the exact input
container.

ASSUMPTION 2 — coordinate frame: `RoadSegment.polyline`'s own field
comment says "real-world meters, site-local frame" (matching
`BuildingFootprint.footprint_polygon`'s identical phrasing). Stage 2's
T2.3 (building footprint extraction) explicitly does a scene-to-real
conversion internally, using the anchor point's scale factor — but T3.2's
own function signature (`segment_road_network(road_mesh_data) ->
List[RoadSegment]`) has no anchor/scale parameter to do the same. This is
implemented assuming `road_mesh_data`'s vertices are ALREADY in real-world
meters (i.e. the scene-to-real conversion happened upstream, before this
function is called) — flagged here since the alternative (accepting scene-
local coordinates and converting internally) is equally plausible and
would need an anchor_point parameter this doc's stated signature doesn't
have. Needs confirming once Stage 2's real pipeline exists.

ASSUMPTION 3 — segmentation approach: connected-component splitting alone
isn't sufficient if `Road_Network` is a single connected mesh representing
the whole road network (a very plausible shape for a small demo site) —
that would yield exactly one "segment" covering everything, which isn't
useful for per-segment exposure scoring. Combines both techniques the
build doc names: connected-component analysis first (splitting genuinely
disjoint road pieces, using face-adjacency via union-find), THEN
fixed-length chunking along each component's own centerline (approximated
via PCA — the first principal axis of the component's vertices), per
`segment_length_m`. Width per segment estimated from the component's
extent along its SECOND principal axis (perpendicular to the direction of
travel) within that segment's own point range.

Per the build doc's own instruction ("If the road mesh doesn't cleanly
decompose into segments... flag this and ask rather than producing an
arbitrary segmentation"): a connected component whose point spread isn't
meaningfully elongated (an intersection blob, a roundabout, or too few
points to define a direction) raises `AmbiguousRoadGeometryError` instead
of forcing a segmentation onto geometry that doesn't support one.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from backend.stage3.shared.contracts import RoadSegment

# Below this fraction, a component's point spread isn't meaningfully
# elongated along one axis (the ratio of its second-to-first principal
# singular values) -- e.g. an intersection blob or roundabout, not a road
# strip a fixed-length chunk along one direction can sensibly represent.
# Flagged as an unverified default, same pattern as this project's other
# assumption-driven thresholds -- not proven correct against a real road
# mesh, since none exists yet to check against.
_MAX_ELONGATION_RATIO_FOR_A_ROAD_STRIP = 0.6

_MIN_POINTS_FOR_A_DIRECTION = 3


class UnsupportedRoadMeshFormatError(Exception):
    """Raised when `road_mesh_data` doesn't match any of the shapes this
    function knows how to read vertices/faces from (see ASSUMPTION 1)."""


class AmbiguousRoadGeometryError(Exception):
    """Raised when a connected component of the road mesh doesn't cleanly
    decompose into a fixed-direction strip (too few points, or not
    meaningfully elongated along one axis) — per the build doc's explicit
    instruction not to force an arbitrary segmentation onto geometry that
    doesn't support one."""


def _extract_vertices_and_faces(
    road_mesh_data: Any,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    vertices_raw: Any = None
    faces_raw: Any = None

    if hasattr(road_mesh_data, "vertices"):
        vertices_raw = road_mesh_data.vertices
        faces_raw = getattr(road_mesh_data, "faces", None)
    elif isinstance(road_mesh_data, dict) and "vertices" in road_mesh_data:
        vertices_raw = road_mesh_data["vertices"]
        faces_raw = road_mesh_data.get("faces")
    else:
        try:
            candidate = np.asarray(road_mesh_data, dtype=float)
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and candidate.ndim == 2 and candidate.shape[1] in (2, 3):
            vertices_raw = candidate

    if vertices_raw is None:
        raise UnsupportedRoadMeshFormatError(
            f"Don't know how to read vertices from road_mesh_data of type "
            f"{type(road_mesh_data)!r} — expected an object/dict with a "
            f"'vertices' attribute/key, or a raw (N, 2|3) array. See this "
            f"module's ASSUMPTION 1 docstring."
        )

    vertices = np.asarray(vertices_raw, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] not in (2, 3):
        raise UnsupportedRoadMeshFormatError(
            f"vertices array has shape {vertices.shape}, expected (N, 2) or (N, 3)"
        )

    faces = None
    if faces_raw is not None:
        faces = np.asarray(faces_raw, dtype=int)

    return vertices, faces


def _connected_components(n_vertices: int, faces: Optional[np.ndarray]) -> list[np.ndarray]:
    """Union-find over face edges. Without faces (a pure point cloud —
    ASSUMPTION 1 covers this input shape too), connectivity can't be
    determined, so the whole vertex set is treated as one component."""
    if faces is None or len(faces) == 0:
        return [np.arange(n_vertices)]

    parent = list(range(n_vertices))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for face in faces:
        for i in range(len(face)):
            union(int(face[i]), int(face[(i + 1) % len(face)]))

    groups: dict[int, list[int]] = {}
    for v in range(n_vertices):
        groups.setdefault(find(v), []).append(v)

    return [np.array(idxs) for idxs in groups.values()]


def _principal_axes(
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Returns (centroid, direction, perpendicular, singular_values) —
    the first two principal axes of `points`, via SVD on the centered
    point set, plus the singular values (used by the caller to detect
    non-elongated / ambiguous geometry)."""
    centroid = points.mean(axis=0)
    centered = points - centroid
    _, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
    direction = vt[0]
    perpendicular = vt[1] if len(vt) > 1 else np.zeros_like(direction)
    return centroid, direction, perpendicular, singular_values


def segment_road_network(
    road_mesh_data: Any, segment_length_m: float = 20.0
) -> list[RoadSegment]:
    """Segment `road_mesh_data`'s road geometry into fixed-length pieces
    per connected component. See this module's docstring for the three
    flagged assumptions this makes about input shape, coordinate frame,
    and algorithm choice — none independently confirmed against a real
    Stage 2 mesh, since Stage 2 doesn't exist in this repo yet.

    Raises `UnsupportedRoadMeshFormatError` if `road_mesh_data` doesn't
    match a known shape, `AmbiguousRoadGeometryError` if a connected
    component's geometry doesn't cleanly support a fixed-direction
    segmentation.
    """
    vertices, faces = _extract_vertices_and_faces(road_mesh_data)
    if vertices.shape[1] == 2:
        # Pad to 3D internally so the same PCA/segmentation code works
        # regardless of whether the input carried a z coordinate.
        vertices = np.hstack([vertices, np.zeros((len(vertices), 1))])

    components = _connected_components(len(vertices), faces)

    segments: list[RoadSegment] = []
    segment_index = 0

    for component_indices in components:
        component_points = vertices[component_indices]

        if len(component_points) < _MIN_POINTS_FOR_A_DIRECTION:
            raise AmbiguousRoadGeometryError(
                f"A road mesh component has only {len(component_points)} "
                f"vertices — too few to determine a direction of travel."
            )

        centroid, direction, perpendicular, singular_values = _principal_axes(
            component_points
        )
        if singular_values[0] <= 0:
            raise AmbiguousRoadGeometryError(
                "A road mesh component has zero extent (all points coincide)."
            )
        elongation_ratio = (
            singular_values[1] / singular_values[0] if len(singular_values) > 1 else 0.0
        )
        if elongation_ratio > _MAX_ELONGATION_RATIO_FOR_A_ROAD_STRIP:
            raise AmbiguousRoadGeometryError(
                f"A road mesh component isn't meaningfully elongated along "
                f"one axis (second/first singular value ratio = "
                f"{elongation_ratio:.2f}, threshold = "
                f"{_MAX_ELONGATION_RATIO_FOR_A_ROAD_STRIP}) — likely an "
                f"intersection or roundabout, not a straight-ish road "
                f"strip a fixed-direction chunking can sensibly segment."
            )

        centered = component_points - centroid
        t = centered @ direction  # 1D coordinate along the direction of travel
        order = np.argsort(t)
        t_sorted = t[order]
        points_sorted = component_points[order]
        perp_coords_sorted = centered[order] @ perpendicular

        t_min, t_max = float(t_sorted[0]), float(t_sorted[-1])
        chunk_start = t_min
        while chunk_start < t_max:
            chunk_end = min(chunk_start + segment_length_m, t_max)
            mask = (t_sorted >= chunk_start) & (t_sorted <= chunk_end)
            if not np.any(mask):
                chunk_start = chunk_end
                continue

            chunk_points = points_sorted[mask]
            width_m = float(
                perp_coords_sorted[mask].max() - perp_coords_sorted[mask].min()
            )
            polyline = [[float(p[0]), float(p[1])] for p in (chunk_points[0], chunk_points[-1])]

            segments.append(
                RoadSegment(
                    segment_id=f"road_seg_{segment_index:03d}",
                    polyline=polyline,
                    width_m=width_m if width_m > 0 else None,
                )
            )
            segment_index += 1
            chunk_start = chunk_end

    return segments
