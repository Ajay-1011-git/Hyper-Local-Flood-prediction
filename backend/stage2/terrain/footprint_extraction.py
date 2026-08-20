"""Building footprint extraction (T2.3, amended 2026-08-20 for real data).

API CONFIRMED IN-SESSION (shapely 2.1.2, trimesh 5.0.0)
------------------------------------------------------------
`shapely.geometry.MultiPoint(points).convex_hull` returns a `Polygon`
whose `.exterior.coords` is the closed ring (first point repeated last) —
confirmed by running it directly against a real 5-point set this session,
not assumed.

FOOTPRINT METHOD: CONVEX HULL, NOT THE EXACT OUTLINE
---------------------------------------------------------
Each building's footprint is the convex hull of its ground-projected
vertices, not its exact (possibly concave) outline. For the simple
rectangular-block buildings this Blender task's naming convention implies
("Building_01" etc.), a convex hull and the true footprint coincide. A
future genuinely concave building would need a proper alpha-shape/
boundary-tracing method instead — flagged here rather than silently
producing a slightly-wrong footprint for that case.

MULTI-PIECE BUILDINGS ARE NORMAL, NOT AMBIGUOUS (real-data correction)
---------------------------------------------------------------------------
An earlier version of this file rejected any building whose mesh split
into more than one connected component, treating that as ambiguous
geometry. The real GLB (once it arrived) showed this was wrong: every real
building is genuinely 5-8 disconnected mesh pieces after the export
pipeline's simplify step (confirmed by listing the real scene graph) —
that's the NORMAL shape for this data, not a sign of an unresolvable
building. T2.1's `load_site_model` already merges same-prefix pieces
before this function ever sees them, so `AmbiguousGeometryError` here is
now reserved for what it should have always meant: a truly degenerate
point set (collinear/coincident vertices that can't form a real polygon
at all) — not "more than one piece."
"""

from __future__ import annotations

from typing import List

import trimesh
from shapely.geometry import MultiPoint

from stage2.shared.contracts import BuildingFootprint
from stage2.terrain.errors import AmbiguousGeometryError
from stage2.terrain.site_transform import SiteTransform


def _footprint_for_mesh(
    building_id: str, mesh: trimesh.Trimesh, site_transform: SiteTransform
) -> BuildingFootprint:
    """Build one `BuildingFootprint` from `mesh` (already merged, world-coordinate).

    Raises:
        AmbiguousGeometryError: if the ground-projected vertices are
            degenerate (collinear/coincident — no real 2D footprint
            exists), not merely "more than one mesh piece" (see module
            docstring for why that's no longer treated as an error).
    """
    real_points = [
        site_transform.scene_to_east_north_m(v[0], v[2]) for v in mesh.vertices
    ]
    hull = MultiPoint(real_points).convex_hull
    if hull.geom_type != "Polygon":
        # A degenerate mesh (all points collinear or coincident) can't
        # produce a real 2D footprint -- flag it, don't fabricate one.
        raise AmbiguousGeometryError(
            f"{building_id}'s ground-projected vertices are degenerate "
            f"(convex hull is a {hull.geom_type}, not a Polygon) — cannot "
            "resolve a footprint."
        )
    polygon_coords = [list(point) for point in hull.exterior.coords]

    # Y is up (confirmed glTF Y-up convention -- see site_transform.py).
    min_y, max_y = mesh.bounds[0][1], mesh.bounds[1][1]
    height_m = float((max_y - min_y) * site_transform.scale)

    return BuildingFootprint(
        building_id=building_id,
        footprint_polygon=polygon_coords,
        height_m=height_m,
    )


def extract_building_footprints(
    buildings: dict[str, trimesh.Trimesh], site_transform: SiteTransform
) -> List[BuildingFootprint]:
    """Derive a `BuildingFootprint` for every building mesh in `buildings`.

    `buildings` should hold only the `Building_*` entries from T2.1's
    `load_site_model` output (not `Road_Network` — this task is buildings
    only, per its own scope), already merged per-building and in real
    world scene coordinates.

    Raises:
        AmbiguousGeometryError: if a building's ground-projected vertices
            are degenerate. Never guesses a footprint for ambiguous
            geometry — ask the human instead (CLAUDE.md rule 2).
    """
    return [
        _footprint_for_mesh(building_id, mesh, site_transform)
        for building_id, mesh in buildings.items()
    ]
