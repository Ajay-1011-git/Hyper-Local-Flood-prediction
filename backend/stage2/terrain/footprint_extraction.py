"""Building footprint extraction (T2.3).

API CONFIRMED IN-SESSION (shapely 2.1.2, trimesh 5.0.0)
------------------------------------------------------------
`shapely.geometry.MultiPoint(points).convex_hull` returns a `Polygon`
whose `.exterior.coords` is the closed ring (first point repeated last) —
confirmed by running it directly against a real 5-point set this session,
not assumed. `trimesh.Trimesh.split(**kwargs) -> list[Trimesh]` splits a
mesh into its connected components — confirmed by splitting a single box
(1 component) and two disconnected boxes (2 components) directly.

FOOTPRINT METHOD: CONVEX HULL, NOT THE EXACT OUTLINE
---------------------------------------------------------
Each building's footprint is the convex hull of its ground-projected
vertices, not its exact (possibly concave) outline. For the simple
rectangular-block buildings this Blender task's naming convention implies
("Building_01" etc., matching the architecture doc's simplified 3-building
demo site), a convex hull and the true footprint coincide. If a future
site has genuinely concave buildings (L-shaped, etc.), this would need a
proper alpha-shape/boundary-tracing method instead — flagged here rather
than silently producing a slightly-wrong footprint for that case.
"""

from __future__ import annotations

from typing import List

import trimesh
from shapely.geometry import MultiPoint

from stage2.shared.contracts import AnchorPoint, BuildingFootprint
from stage2.terrain.anchor_transform import scene_offset_to_east_north_m
from stage2.terrain.errors import AmbiguousGeometryError


def _footprint_for_mesh(
    building_id: str, mesh: trimesh.Trimesh, anchor: AnchorPoint
) -> BuildingFootprint:
    """Build one `BuildingFootprint` from a single connected mesh piece.

    Raises:
        AmbiguousGeometryError: if the mesh is not one connected piece —
            the caller (`extract_building_footprints`) checks this before
            calling here; kept as a second check so this function is safe
            to call directly too.
    """
    pieces = mesh.split()
    if len(pieces) != 1:
        raise AmbiguousGeometryError(
            f"{building_id}'s mesh has {len(pieces)} disconnected pieces; "
            "cannot resolve to a single footprint without guessing which "
            "piece(s) are the real building."
        )

    ground_points = [
        scene_offset_to_east_north_m(vertex, anchor) for vertex in mesh.vertices
    ]
    hull = MultiPoint(ground_points).convex_hull
    if hull.geom_type != "Polygon":
        # A degenerate mesh (all points collinear or coincident) can't
        # produce a real 2D footprint -- flag it, don't fabricate one.
        raise AmbiguousGeometryError(
            f"{building_id}'s ground-projected vertices are degenerate "
            f"(convex hull is a {hull.geom_type}, not a Polygon) — cannot "
            "resolve a footprint."
        )
    polygon_coords = [list(point) for point in hull.exterior.coords]

    min_z, max_z = mesh.bounds[0][2], mesh.bounds[1][2]
    height_m = float((max_z - min_z) * anchor.scene_to_real_scale_factor)

    return BuildingFootprint(
        building_id=building_id,
        footprint_polygon=polygon_coords,
        height_m=height_m,
    )


def extract_building_footprints(
    buildings: dict[str, trimesh.Trimesh], anchor: AnchorPoint
) -> List[BuildingFootprint]:
    """Derive a `BuildingFootprint` for every building mesh in `buildings`.

    `buildings` should hold only the `Building_*` entries from T2.1's
    `load_site_model` output (not `Road_Network` — this task is buildings
    only, per its own scope).

    Raises:
        AmbiguousGeometryError: if any building's mesh is not a single
            connected, non-degenerate piece. Never guesses a footprint for
            ambiguous geometry — ask the human instead (CLAUDE.md rule 2).
    """
    return [
        _footprint_for_mesh(building_id, mesh, anchor)
        for building_id, mesh in buildings.items()
    ]
