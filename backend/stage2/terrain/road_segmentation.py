"""Road segmentation (T2.4 extension, 2026-08-20): derive real `RoadSegment`s
from the site's real `Road_Network` mesh, for use by
`mesh/computational_mesh.py`'s road-node tagging.

WHY THIS EXISTS (real cross-stage gap, found during a full-system audit)
--------------------------------------------------------------------------
Stage 3's `rank_structures` (T3.5) needs to attribute hazard to a
`RoadSegment` via `NodeState.road_segment_id` — the same mechanism already
used for buildings (`NodeState.building_id`, populated from
`ComputationalMeshNode.building_id` via `_tag_wall_node`). No equivalent
existed for roads: `Road_Network` was loaded (`ingestion/glb_loader.py`,
per `REQUIRED_OBJECT_NAMES`) but never used beyond that — this stage's own
`footprint_extraction.py` explicitly scoped itself to buildings only. This
module closes that gap. Touching `backend/stage2/` for this was explicitly
authorized by the project owner (2026-08-20), same one-off pattern already
used for the Stage 1B DEM fix (see `stage1b/CLAUDE.md`'s addendum).

METHOD: SPATIAL GRID BINNING, NOT A SINGLE PRINCIPAL AXIS
--------------------------------------------------------------
A first version of this module used a single global PCA/SVD principal-axis
fit (mirroring how Stage 3's own T3.2 handles an ALREADY-CONNECTED-
COMPONENT-SEPARATED road strip). Real-tested directly against the real
`vit_vellore_site.glb`'s actual `Road_Network` mesh (3408 vertices,
spanning a real ~220m x 130m footprint) and it FAILED its own ambiguity
check (elongation_ratio=0.61, just over the 0.6 threshold) — a real campus
road network is a loop/branching network, not one straight corridor, so no
single principal axis meaningfully represents it. Rather than loosen the
threshold to force a wrong-shaped straight-line segmentation through, this
was redesigned to bin the real-world road points into a fixed-size spatial
grid (`cell_size_m`) and treat each occupied cell as one segment —
topology-agnostic by construction (handles loops, branches, curves, dead
ends, anything) instead of assuming a single corridor direction.

WHY NOT REUSE STAGE 3'S OWN T3.2 ROAD SEGMENTATION
--------------------------------------------------------
`backend/stage3/exposure/road_segmentation.py` already does something
similar, but importing it here would make Stage 2 depend on Stage 3 —
backwards per this project's stage ordering (Stage 3 depends on Stage 2's
output, never the reverse). Also, T3.2 assumes its input mesh is ALREADY
one connected, elongated strip (per its own docstring) — exactly the
assumption that failed against this site's real network topology above,
so its approach wasn't a fit here even setting the dependency-direction
issue aside.

SIMPLIFICATION, FLAGGED
------------------------
Each segment's `polyline` is its grid cell's real-world bounding diagonal
(min/max corner), not a true road centerline — sufficient for this
module's only real consumer (`tag_road_node`'s point-to-polyline distance
check, which just needs "is this point near segment N"), but not a
geometrically faithful road shape. `cell_size_m` (default 20.0, same
order of magnitude as the buffer/segment-length defaults used elsewhere
in this project) is a flagged, unverified-optimal default — smaller
values give finer-grained (but more numerous) segments.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import trimesh
from shapely.geometry import LineString, Point

from stage2.shared.contracts import RoadSegment
from stage2.terrain.errors import TerrainError
from stage2.terrain.site_transform import SiteTransform

# Flagged per this project's convention for unverified defaults (same
# pattern as other proximity thresholds throughout this codebase): half
# of a plausible campus-road width (~7-8m) plus a small margin. Not an
# independently surveyed value.
ROAD_TAGGING_BUFFER_M = 4.0

# Grid cell size for road segmentation (see module docstring's METHOD
# section) — same order of magnitude as Stage 3's own T3.2 default
# segment length (20.0m), not independently re-derived.
DEFAULT_CELL_SIZE_M = 20.0


class AmbiguousRoadGeometryError(TerrainError):
    """`Road_Network` has no real-world points to segment at all — never
    fabricate a segment for geometry that isn't there."""


def extract_road_segments(
    road_mesh: trimesh.Trimesh,
    site_transform: SiteTransform,
    cell_size_m: float = DEFAULT_CELL_SIZE_M,
) -> List[RoadSegment]:
    """Bin `road_mesh`'s real-world (east_m, north_m) vertices into a
    `cell_size_m` spatial grid; each occupied cell becomes one
    `RoadSegment` (see module docstring's METHOD section for why binning,
    not a single principal-axis fit).

    Segment ids are assigned in a deterministic order (sorted by grid
    row then column), not mesh-vertex-iteration order — re-running this
    against the same mesh always produces the same ids for the same
    physical cells, per this project's idempotency convention.

    Raises:
        AmbiguousRoadGeometryError: `road_mesh` has zero vertices.
    """
    points = np.array(
        [site_transform.scene_to_east_north_m(v[0], v[2]) for v in road_mesh.vertices]
    )
    if len(points) == 0:
        raise AmbiguousRoadGeometryError("Road_Network has no real-world vertices to segment.")

    cell_indices = np.floor(points / cell_size_m).astype(int)
    cells: Dict[Tuple[int, int], List[np.ndarray]] = {}
    for (row, col), point in zip(map(tuple, cell_indices), points):
        cells.setdefault((row, col), []).append(point)

    segments: List[RoadSegment] = []
    for i, cell_key in enumerate(sorted(cells.keys())):
        cell_points = np.array(cells[cell_key])
        min_corner = cell_points.min(axis=0)
        max_corner = cell_points.max(axis=0)
        segments.append(
            RoadSegment(
                segment_id=f"Road_Segment_{i:03d}",
                polyline=[
                    [float(min_corner[0]), float(min_corner[1])],
                    [float(max_corner[0]), float(max_corner[1])],
                ],
            )
        )
    return segments


def tag_road_node(
    east_m: float,
    north_m: float,
    segments: List[RoadSegment],
    buffer_m: float = ROAD_TAGGING_BUFFER_M,
) -> str | None:
    """Return the nearest `RoadSegment.segment_id` if `(east_m, north_m)`
    is within `buffer_m` of it (real point-to-polyline distance via
    shapely, not an approximation), else `None`. `segments=[]` always
    returns `None` (an untagged, open-terrain cell — never fabricated)."""
    if not segments:
        return None
    point = Point(east_m, north_m)
    best_id: str | None = None
    best_distance = float("inf")
    for seg in segments:
        distance = LineString(seg.polyline).distance(point)
        if distance < best_distance:
            best_distance = distance
            best_id = seg.segment_id
    return best_id if best_distance <= buffer_m else None
