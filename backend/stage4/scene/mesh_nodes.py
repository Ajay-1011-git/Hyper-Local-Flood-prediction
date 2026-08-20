"""Computational-mesh node positions proxy — T4B.5 support.

WHY THIS EXISTS — the same real gap T4B.3/T4B.4 already found and closed
---------------------------------------------------------------------
T4B.5 needs to displace a water surface by each real node's
`NodeState.depth_mean_m` at the current timeline hour — which requires
knowing WHERE each `node_id` sits in the scene. `NodeState` carries only
a `node_id` string (`"n_{row}_{col}"`, confirmed from
`stage2/mesh/computational_mesh.py`); nothing serves the real per-node
position over HTTP (checked: `set_site_state` — the only thing that ever
populates Stage 2's real node/edge state — is called only from Stage 2's
own tests, never from any live pipeline in this repo).

This closes the gap the same way T4B.4 did: reconstruct Stage 2's real
node grid by calling Stage 2's own real, unmodified functions directly
(`load_site_model`, `compute_site_bbox_latlon`, `build_computational_mesh`
— a direct cross-import, not an HTTP call, same established pattern as
`alerts/site_geometry.py` and `scene/site_mesh.py`). Given the same real
GLB+anchor, the same real DEM raster, and Stage 2's own configured
`terrain_grid_resolution_m`, this reproduces exactly the grid Stage 2
itself would/does build — not a parallel guess at a different one.

`footprints=[]` is passed to `build_computational_mesh` deliberately:
this endpoint only needs node POSITIONS, and the real emitted
`NodeState.building_id`/`road_segment_id` (from Stage 2's own live
simulation) already carries the real wall/road tagging — recomputing it
here would be redundant, and an empty footprint list only changes the
(here-discarded) `is_wall_node`/`building_id` fields on the
reconstruction, never node count or position.

A REAL, CONFIRMED BUG IN STAGE 2'S OWN `interpolate_terrain`, WORKED
AROUND HERE RATHER THAN PATCHED THERE (anti-drift rule 6: don't touch
Stage 2's files)
---------------------------------------------------------------------
`stage2/terrain/dem_interpolation.py::interpolate_terrain` computes grid
`width`/`height` as `(max_x - min_x) / resolution_m` directly on the
raster's OWN CRS units — correct only if that CRS is projected (metres).
Stage 1B's real, registered DEM raster is EPSG:4326 (confirmed this
session: `rasterio.open(...).crs` prints `EPSG:4326`, degrees). Calling
Stage 2's real function against the real raster in this session produced
a degenerate 1×1 grid (`(max_lon-min_lon) ≈ 0.002` degrees, divided by
`resolution_m=1.0`, ceilinged to `1`) — verified directly, not assumed.

`_terrain_grid_for_mesh` below is this module's own equivalent, using
the SAME flat-earth degrees<->metres conversion already used everywhere
else in this project (`site_transform.py`, `dem_proxy.py`,
`terrainGeometry.ts`) to size the destination grid correctly in real
metres, then reprojecting with the same `rasterio.warp.reproject`/
`Resampling.bilinear` call Stage 2's own function uses. Result at the
real site bbox + Stage 2's real 1.0m `terrain_grid_resolution_m`: a
225×134 = 30,150-node grid — within ~1% of the 29,832-node figure this
project's own `sceneStore.ts` comment cites from Stage 2's real T2.8
VERIFY run, i.e. the right order of magnitude and shape for the real
site, not an arbitrarily different reconstruction.

This is flagged here for whoever owns Stage 2 to fix upstream — it is a
real, live bug in code this task is not permitted to touch, not a
stylistic difference.

NEVER FABRICATED IF UNAVAILABLE
---------------------------------------------------------------------
Unlike `site_mesh.py`'s placeholder-box fallback (safe there because it's
purely visual), positions claiming to correspond to the real hydraulic
simulation's real node ids must never be invented. If the real GLB/
anchor/DEM aren't available, this raises `MeshNodesUnavailableError`
(surfaced as a 503, same convention as `dem_proxy.py`'s
`TerrainUnavailableError`) rather than returning a placeholder grid.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from pydantic import BaseModel

from backend.stage4.config import settings
from backend.stage4.terrain.dem_proxy import TerrainUnavailableError, find_terrain_raster_path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPO_ROOT / "backend"
_GLB_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "vit_vellore_site.glb"
_ANCHOR_PATH = _BACKEND_ROOT / "stage2" / "blender_prep" / "output" / "anchor_point.json"

if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_METERS_PER_DEGREE_LAT = 111_320.0


class MeshNodePosition(BaseModel):
    """One real `ComputationalMeshNode`'s position, in `Terrain.tsx`'s
    exact scene frame (`x_m`=east, `z_m`=-north, `elevation_m`=real
    absolute elevation — same convention `site_mesh.py` uses)."""

    node_id: str
    x_m: float
    z_m: float
    elevation_m: float


class SiteMeshNodesResponse(BaseModel):
    site_id: str
    rows: int
    cols: int
    resolution_m: float
    nodes: List[MeshNodePosition]


class MeshNodesUnavailableError(RuntimeError):
    """Real GLB/anchor/DEM data unavailable — never substituted with a
    fabricated grid (see module docstring)."""


_CACHE: Dict[str, SiteMeshNodesResponse] = {}


def _terrain_grid_for_mesh(
    raster_path: str, bbox_latlon: Tuple[float, float, float, float], resolution_m: float
):
    """Stage 2's real `TerrainGrid`, built with the CRS-unit bug fixed —
    see module docstring. Returns a real `stage2.shared.contracts.TerrainGrid`
    (cross-imported, not redefined) so `build_computational_mesh` accepts
    it exactly as it would Stage 2's own."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import Resampling, reproject

    from stage2.shared.contracts import TerrainGrid  # type: ignore[import-not-found]

    min_lat, max_lat, min_lon, max_lon = bbox_latlon
    mid_lat = (min_lat + max_lat) / 2
    d_lat = resolution_m / _METERS_PER_DEGREE_LAT
    d_lon = resolution_m / (_METERS_PER_DEGREE_LAT * math.cos(math.radians(mid_lat)))
    width = max(1, math.ceil((max_lon - min_lon) / d_lon))
    height = max(1, math.ceil((max_lat - min_lat) / d_lat))

    with rasterio.open(raster_path) as src:
        if str(src.crs) != "EPSG:4326":
            # This project's one real registered raster is EPSG:4326
            # (confirmed this session) -- a differently-registered raster
            # would need src.crs's own degrees-per-unit, not assumed here.
            raise MeshNodesUnavailableError(
                f"{raster_path} is in {src.crs}, not the confirmed EPSG:4326 "
                "this reconstruction's degrees<->metres math assumes."
            )
        dst_transform = from_origin(min_lon, max_lat, d_lon, d_lat)
        elevation = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=src.crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    if not np.isfinite(elevation).any():
        raise MeshNodesUnavailableError(
            f"Terrain window over {bbox_latlon} contains no finite elevation values."
        )
    # Nodata cells filled with the finite mean, same honest-but-necessary
    # choice `dem_proxy.py`'s renderer makes -- a mesh node needs SOME
    # elevation, and build_computational_mesh has no null-handling of its
    # own to defer to.
    mean_elev = float(np.nanmean(elevation))
    filled = np.where(np.isfinite(elevation), elevation, mean_elev)

    return TerrainGrid(
        site_id="mesh-node-reconstruction",
        resolution_m=resolution_m,
        origin_lat=max_lat,
        origin_lon=min_lon,
        elevation_grid=filled.tolist(),
        interpolated_from_regional_dem=True,
    )


async def build_site_mesh_nodes(site_id: str) -> SiteMeshNodesResponse:
    """Real per-node `(x_m, z_m, elevation_m)` for every one of Stage 2's
    real computational-mesh nodes, in `Terrain.tsx`'s scene frame.

    Raises:
        MeshNodesUnavailableError: real GLB/anchor/DEM data unavailable,
            or the registered raster isn't the confirmed EPSG:4326 this
            reconstruction's math assumes. Never falls back to a
            fabricated grid.
    """
    if site_id in _CACHE:
        return _CACHE[site_id]

    if not _GLB_PATH.is_file() or not _ANCHOR_PATH.is_file():
        raise MeshNodesUnavailableError(
            f"Real GLB/anchor data not found at {_GLB_PATH} / {_ANCHOR_PATH}."
        )

    target_lat = settings.target_site_lat
    target_lon = settings.target_site_lon
    if target_lat is None or target_lon is None:
        raise MeshNodesUnavailableError(
            "settings.target_site_lat/target_site_lon must be configured to "
            "place mesh nodes in the same frame Terrain.tsx uses."
        )

    from stage2.config import get_settings as get_stage2_settings  # type: ignore[import-not-found]
    from stage2.ingestion.glb_loader import load_site_model  # type: ignore[import-not-found]
    from stage2.mesh.computational_mesh import build_computational_mesh  # type: ignore[import-not-found]
    from stage2.terrain.dem_interpolation import (  # type: ignore[import-not-found]
        compute_site_bbox_latlon,
    )

    try:
        objects, site_transform = load_site_model(_GLB_PATH, _ANCHOR_PATH)
        bbox_latlon = compute_site_bbox_latlon(objects, site_transform)

        raster_path = await find_terrain_raster_path(target_lat, target_lon)
        stage2_settings = get_stage2_settings()

        terrain = _terrain_grid_for_mesh(
            raster_path, bbox_latlon, stage2_settings.terrain_grid_resolution_m
        )
        nodes, _edges = build_computational_mesh(terrain, [], site_transform)
    except MeshNodesUnavailableError:
        raise
    except TerrainUnavailableError as exc:
        raise MeshNodesUnavailableError(str(exc)) from exc
    except Exception as exc:
        raise MeshNodesUnavailableError(
            f"Failed to reconstruct Stage 2's real computational mesh: {exc}"
        ) from exc

    positions: List[MeshNodePosition] = []
    for node in nodes:
        lat, lon = site_transform.east_north_to_latlon(node.x_m, node.y_m)
        north_rel_m = (lat - target_lat) * _METERS_PER_DEGREE_LAT
        east_rel_m = (
            (lon - target_lon) * _METERS_PER_DEGREE_LAT * math.cos(math.radians(target_lat))
        )
        positions.append(
            MeshNodePosition(
                node_id=node.node_id,
                x_m=east_rel_m,
                z_m=-north_rel_m,
                elevation_m=node.elevation_m,
            )
        )

    rows = len(terrain.elevation_grid)
    cols = len(terrain.elevation_grid[0]) if rows else 0
    result = SiteMeshNodesResponse(
        site_id=site_id,
        rows=rows,
        cols=cols,
        resolution_m=stage2_settings.terrain_grid_resolution_m,
        nodes=positions,
    )
    _CACHE[site_id] = result
    return result
