"""Computational mesh assembly (T2.4, amended 2026-08-20 for real georeferencing).

REAL EXPECTED GRAPH SHAPE — CONFIRMED IN-SESSION AGAINST RBTV1/mSWE-GNN
---------------------------------------------------------------------------
Fetched and read `database/graph_creation.py` (function
`convert_mesh_to_pyg`) and `models/gnn.py` directly from
github.com/RBTV1/mSWE-GNN this session, not assumed:

- Graph nodes are mesh CELLS (this project's terrain grid cells / building-
  tagged cells), not triangle vertices. `models/gnn.py`'s `GNN.forward`
  reads `graph.x` (node features), `graph.edge_index`, `graph.edge_attr`
  directly off a PyG-style object.
- `edge_index` connects neighboring cells (`mesh.dual_edge_index` —
  "index of connected faces"), i.e. a real adjacency graph between grid
  cells, exactly what this task's own prompt asks `build_computational_mesh`
  to derive.
- `edge_attr` carries `face_distance` (distance between cell centers) and
  `edge_slope` (`DEM_diff / face_distance`) — this project's `MeshEdge`
  contract (`shared/contracts.py`, authored this session) names its two
  fields `distance_m`/`slope` to match that mapping directly, not
  independently invented.
- Wall/obstacle nodes are NOT excluded from the graph in the real model —
  confirmed no cell-removal logic in `convert_mesh_to_pyg`; boundary
  handling there is via a separate ghost-cell mechanism
  (`data.node_BC`/`data.BC`). This project's `ComputationalMeshNode.
  is_wall_node` flag matches that: wall cells stay IN the graph (get real
  edges to their neighbors) and the no-flow behavior is enforced by
  whatever consumes `is_wall_node` (T2.5's solver, T2.6's GNN) — not by
  this task removing edges.

REGULAR GRID, NOT A TRIANGULATION
--------------------------------------
Unlike mSWE-GNN's own triangulated meshes, this project's terrain is a
regular grid (T2.2's `TerrainGrid`), so adjacency here is the simpler
4-connectivity (N/S/E/W neighbors) standard for finite-volume/finite-
difference regular grids — not derived from a Delaunay/Triangle import
like the source repo's `convert_mesh_to_pyg` does. The resulting
node/edge SHAPE (cell-centered nodes, distance+slope edge features) still
matches what the model actually consumes.

RAISED TERRAIN FEATURES (not walls) — confirmed with the project owner
---------------------------------------------------------------------------
The site design has a raised circular garden bed in front of the MGR
block (`Garden_Bed_Ring`, per the real GLB's node names). Confirmed
directly (2026-08-20): this is NOT an obstacle like a building — water
should only cross it once flood depth exceeds the garden's real raised
height. That's exactly what a plain ELEVATION OFFSET achieves through
this solver's own normal physics (T2.5's water-surface-slope term) —
no special wall-node handling needed, just adding the feature's real
height (from its own mesh Y-extent) to terrain elevation under its
footprint. `raised_terrain_features` implements this generically for any
future such feature, not hardcoded to one object name.

`Building_01`/`Building_02` (confirmed genuine obstacles, per the same
conversation) still use `is_wall_node`/`footprints` as before.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import Point, Polygon

from stage2.mesh.errors import DoubleTaggedNodeError
from stage2.shared.contracts import (
    BuildingFootprint,
    ComputationalMeshNode,
    MeshEdge,
    RoadSegment,
    TerrainGrid,
)
from stage2.terrain.road_segmentation import ROAD_TAGGING_BUFFER_M, tag_road_node
from stage2.terrain.site_transform import SiteTransform


def _tag_wall_node(
    east_m: float, north_m: float, footprints: List[BuildingFootprint]
) -> Tuple[bool, str | None]:
    """Return (is_wall_node, building_id) for one grid cell's position.

    Raises:
        DoubleTaggedNodeError: if the point falls inside more than one
            building's footprint.
    """
    point = Point(east_m, north_m)
    matches = [
        fp.building_id
        for fp in footprints
        if Polygon(fp.footprint_polygon).contains(point)
    ]
    if len(matches) > 1:
        raise DoubleTaggedNodeError(
            f"Point ({east_m:.2f}, {north_m:.2f}) falls inside {len(matches)} "
            f"building footprints: {matches}. Footprints should not overlap."
        )
    if matches:
        return True, matches[0]
    return False, None


def _raised_elevation_offset_m(
    east_m: float, north_m: float, raised_terrain_features: List[Tuple[BuildingFootprint, float]]
) -> float:
    """Sum of raise heights for every raised feature whose footprint contains this point.

    Not mutually exclusive with `_tag_wall_node` -- a cell can be both
    inside a raised feature's footprint and (separately) tagged/untagged
    as a wall; the two mechanisms are orthogonal (obstacle vs. terrain
    height), per the confirmed physical model.
    """
    point = Point(east_m, north_m)
    return sum(
        raise_m
        for footprint, raise_m in raised_terrain_features
        if Polygon(footprint.footprint_polygon).contains(point)
    )


def build_computational_mesh(
    terrain: TerrainGrid,
    footprints: List[BuildingFootprint],
    site_transform: SiteTransform,
    raised_terrain_features: Optional[List[Tuple[BuildingFootprint, float]]] = None,
    road_segments: Optional[List[RoadSegment]] = None,
    road_tagging_buffer_m: float = ROAD_TAGGING_BUFFER_M,
) -> Tuple[List[ComputationalMeshNode], List[MeshEdge]]:
    """Combine `terrain` and `footprints` into the finite-volume mesh graph.

    `site_transform` is required beyond the doc's literal
    `(terrain, footprints)` signature: `TerrainGrid` is natively in
    lat/lon (T2.2's output), `BuildingFootprint` is natively in real
    east/north meters (T2.3's output, via the same `SiteTransform`) — the
    two coordinate frames only reconcile through it. Without it,
    point-in-polygon tagging would be comparing incompatible frames.

    `raised_terrain_features`: `(footprint, raise_height_m)` pairs for
    terrain that's elevated but NOT an obstacle (e.g. a raised garden bed)
    — see module docstring. Applied as a pure elevation offset, never
    `is_wall_node`.

    `road_segments` (2026-08-20 addition): real `RoadSegment`s from
    `terrain/road_segmentation.py`'s `extract_road_segments`, in the same
    real east/north frame as `footprints`. Cells within
    `road_tagging_buffer_m` of a segment get `road_segment_id` set —
    mirrors `building_id`'s point-in-polygon tagging, but distance-to-
    polyline instead (roads are lines, not closed polygons). `None`
    (the default) tags nothing, matching the honest "no road data" case
    rather than fabricating segment ids.

    Returns `(nodes, edges)`: one `ComputationalMeshNode` per terrain grid
    cell (position in real east/north meters, matching `BuildingFootprint`'s
    frame), tagged `is_wall_node`/`building_id`/`road_segment_id` via real
    geometric tests — never an approximation. `edges` connects each cell to
    its 4-connected (N/S/E/W) neighbors, carrying real distance and
    DEM-slope, matching RBTV1/mSWE-GNN's confirmed `edge_attr` shape (see
    module docstring).

    Raises:
        DoubleTaggedNodeError: if any cell's position falls inside more
            than one building's footprint.
    """
    raised_terrain_features = raised_terrain_features or []
    road_segments = road_segments or []
    elevation = np.asarray(terrain.elevation_grid, dtype=float)
    height, width = elevation.shape

    node_id_grid: List[List[str]] = [[""] * width for _ in range(height)]
    nodes: List[ComputationalMeshNode] = []
    positions: Dict[str, Tuple[float, float]] = {}

    for row in range(height):
        for col in range(width):
            # NOTE: TerrainGrid (§B.2) carries only origin_lat/origin_lon in
            # degrees + resolution_m, not the real projected CRS/transform
            # T2.2 actually resampled onto internally. So each cell's real-
            # world position is reconstructed here via the same flat-earth
            # approximation `SiteTransform` uses elsewhere (consistent
            # method, but it's a second approximation layered on top of
            # T2.2's own DEM-interpolation approximation) -- an accuracy
            # limitation of the contract as specified, not hidden here.
            lat = terrain.origin_lat - row * (terrain.resolution_m / 111_320.0)
            lon = terrain.origin_lon + col * (
                terrain.resolution_m
                / (111_320.0 * np.cos(np.radians(terrain.origin_lat)))
            )
            east_m, north_m = site_transform.latlon_to_east_north_m(lat, lon)

            node_id = f"n_{row}_{col}"
            node_id_grid[row][col] = node_id
            positions[node_id] = (east_m, north_m)

            is_wall, building_id = _tag_wall_node(east_m, north_m, footprints)
            raise_offset = _raised_elevation_offset_m(
                east_m, north_m, raised_terrain_features
            )
            # Only tag roads on non-wall cells -- a building interior cell
            # is never simultaneously "on a road" in this site's real
            # geometry (roads and buildings don't overlap), and skipping
            # the check there avoids a wasted distance computation over
            # every wall cell.
            road_segment_id = (
                None
                if is_wall
                else tag_road_node(east_m, north_m, road_segments, road_tagging_buffer_m)
            )
            nodes.append(
                ComputationalMeshNode(
                    node_id=node_id,
                    x_m=east_m,
                    y_m=north_m,
                    elevation_m=float(elevation[row, col]) + raise_offset,
                    is_wall_node=is_wall,
                    building_id=building_id,
                    road_segment_id=road_segment_id,
                )
            )

    edges: List[MeshEdge] = []
    for row in range(height):
        for col in range(width):
            this_id = node_id_grid[row][col]
            this_node = nodes[row * width + col]
            this_elev = this_node.elevation_m
            this_x, this_y = positions[this_id]
            # Only look right and down -- each undirected edge is added once.
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = row + dr, col + dc
                if nr >= height or nc >= width:
                    continue
                other_id = node_id_grid[nr][nc]
                other_node = nodes[nr * width + nc]
                other_elev = other_node.elevation_m
                other_x, other_y = positions[other_id]
                distance_m = float(np.hypot(other_x - this_x, other_y - this_y))
                slope = (
                    (other_elev - this_elev) / distance_m if distance_m > 0 else 0.0
                )
                edges.append(
                    MeshEdge(
                        node_id_a=this_id,
                        node_id_b=other_id,
                        distance_m=distance_m,
                        slope=slope,
                    )
                )

    return nodes, edges
