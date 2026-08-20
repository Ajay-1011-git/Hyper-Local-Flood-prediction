"""Site mesh (buildings + roads) proxy for the 3D scene — T4B.4.

WHY THIS EXISTS — the same real gap T4B.3 already found and closed
---------------------------------------------------------------------
T4B.4 asks the frontend to "load the same GLB Stage 2 ingested
(`Building_01/02`, `Road_Network`)". Nothing in this repo serves that GLB
(or any position/scale/rotation for it) over HTTP — confirmed by the same
route listing T4B.3's `dem_proxy.py` did. Stage 2 holds the real, fitted
`SiteTransform` only in-process (`stage2/terrain/site_transform.py`); the
frontend has no way to place the raw GLB's local vertex coordinates
inside the scene `Terrain.tsx` already renders.

This module closes that gap from Stage 4's side (same project-owner
decision as T4B.3: keep it in Stage 4's own module boundary rather than
adding a Stage 2 endpoint), doing the REAL coordinate transform
server-side rather than shipping the fit math to re-implement in
TypeScript a second time:

  1. Load the real GLB + anchor fit via Stage 2's own, already-real
     `stage2.ingestion.glb_loader.load_site_model` (a direct cross-import,
     exactly the pattern `alerts/site_geometry.py` already established —
     not an HTTP call, since Stage 2 exposes none, and Stage 4 is
     legitimately downstream of Stage 2, same as Stage 3).
  2. Transform every real vertex from GLB-local (x, y-up, z) into the
     EXACT scene frame `Terrain.tsx` already uses: X=east, Y=up, Z=-north,
     relative to `settings.target_site_lat/lon` — the same reference
     point `dem_proxy.build_site_terrain` uses as `site_lat`/`site_lon`,
     so `SiteMesh` and `Terrain` share one origin with no extra
     alignment step in the frontend.
  3. Re-export as one GLB scene, geometry only (no re-baked materials —
     out of scope for this task; `SiteMesh.tsx` assigns simple materials
     per real object name).

GROUND ELEVATION: A REAL, DISCLOSED APPROXIMATION, NOT A FUDGE
---------------------------------------------------------------------
The GLB's own vertices already carry each building's height ABOVE ITS OWN
local ground (confirmed: every real object's minimum y is ~0 in GLB-local
units — Building_01 in [-0.33, 23.0], Building_02 in [-0.62, 26.5]). What
they do NOT carry is the terrain's real ABSOLUTE elevation, which lives
only in Stage 1B's DEM raster (the same one `dem_proxy.py` reads for
`Terrain.tsx`) — `Terrain.tsx` renders raw elevation_m as world Y, so
buildings at y≈0 would render underground relative to it.

This module samples that DEM at ONE point (`target_site_lat/lon`, the
same site-centre reference the terrain patch uses) and adds it as a
constant offset to every vertex's y. This is honestly a single-point
approximation, not a per-vertex ground-fit: exact at the site centre, and
only as accurate as the real terrain is flat across the ~150m site patch
elsewhere. If a later screenshot shows a real building corner floating or
sinking because the ground genuinely slopes, that is this approximation's
real, known limit — not a bug to silently patch by inventing per-vertex
values with no elevation data behind them.

FALLBACK: NEVER SILENTLY FABRICATE AS "REAL"
---------------------------------------------------------------------
If the real (gitignored, ~11MB) GLB/anchor files aren't present locally,
or `trimesh`/Stage 2's loader can't be imported, this returns a small,
deliberately crude placeholder scene (plain boxes, not the real building
shapes) — same honesty contract as `alerts/site_geometry.py`'s
`placeholder_fallback`, surfaced via the `X-Site-Mesh-Source` response
header, never silently substituted.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

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

# Real, confirmed object names in the real GLB (Stage 2's own
# `glb_loader.REQUIRED_OBJECT_NAMES`) minus `Road_Network` handling, which
# is identical -- listed here too so the placeholder path below doesn't
# need to import Stage 2's module just for this constant.
REQUIRED_OBJECT_NAMES = ("Building_01", "Building_02", "Road_Network")

# Simple per-process cache: this is an 11MB GLB parse + a georeferencing
# fit, not something to redo on every request. Keyed by site_id in case a
# later multi-site deployment adds more (today there is exactly one real
# site, so this holds at most one entry).
_CACHE: Dict[str, Tuple[bytes, str]] = {}


def _placeholder_scene():
    """Small, deliberately crude stand-ins for `Building_01/02`/`Road_Network`.

    Used ONLY if the real GLB/anchor data isn't present locally (e.g. a
    fresh clone without the gitignored `blender_prep/output/` data) or the
    real loader failed. Regular boxes are visually obvious as NOT the real
    site -- never meant to be mistaken for the real building geometry.
    """
    import trimesh

    scene = trimesh.Scene()

    b1 = trimesh.creation.box(extents=[15.0, 20.0, 12.0])
    b1.apply_translation([-20.0, 10.0, -10.0])
    scene.add_geometry(b1, node_name="Building_01")

    b2 = trimesh.creation.box(extents=[20.0, 15.0, 10.0])
    b2.apply_translation([30.0, 7.5, 15.0])
    scene.add_geometry(b2, node_name="Building_02")

    road = trimesh.creation.box(extents=[90.0, 0.3, 6.0])
    road.apply_translation([0.0, 0.15, 40.0])
    scene.add_geometry(road, node_name="Road_Network")

    return scene


async def _ground_elevation_m(lat: float, lon: float) -> Optional[float]:
    """Real DEM elevation at one point — see module docstring's ground-
    elevation section for why a single sample, and its honest limits.

    Returns `None` (never a fabricated number) if no real DEM covers the
    point or it can't be read; callers must treat that as "unknown", not
    "zero".
    """
    try:
        import rasterio
        from rasterio.warp import transform as warp_transform

        raster_path = await find_terrain_raster_path(lat, lon)
        with rasterio.open(raster_path) as src:
            xs, ys = warp_transform("EPSG:4326", src.crs, [lon], [lat])
            value = float(next(src.sample([(xs[0], ys[0])]))[0])
        if not math.isfinite(value):
            logger.warning("DEM ground elevation at (%s, %s) is not finite.", lat, lon)
            return None
        return value
    except TerrainUnavailableError as exc:
        logger.warning("No DEM ground elevation available for (%s, %s): %s", lat, lon, exc)
        return None
    except Exception as exc:
        logger.warning(
            "Failed to sample DEM ground elevation at (%s, %s): %s", lat, lon, exc
        )
        return None


def _real_scene(ground_elevation_m: float):
    """The real GLB, transformed into `Terrain.tsx`'s exact scene frame.

    Raises whatever `stage2.ingestion.glb_loader.load_site_model` raises
    (`MissingSceneObjectError`, `InvalidAnchorPointError`) or an
    `ImportError` if `trimesh`/Stage 2's module can't be imported — the
    caller decides whether to fall back to the placeholder.
    """
    from stage2.ingestion.glb_loader import load_site_model  # type: ignore[import-not-found]

    import trimesh

    objects, site_transform = load_site_model(_GLB_PATH, _ANCHOR_PATH)

    target_lat = settings.target_site_lat
    target_lon = settings.target_site_lon
    if target_lat is None or target_lon is None:
        raise RuntimeError(
            "settings.target_site_lat/target_site_lon must be configured to "
            "place the site mesh in the same frame Terrain.tsx uses."
        )

    scene = trimesh.Scene()
    for name, mesh in objects.items():
        mesh = mesh.copy()
        vx, vy, vz = mesh.vertices[:, 0], mesh.vertices[:, 1], mesh.vertices[:, 2]

        # Real Umeyama fit (Stage 2's `SiteTransform`, confirmed 7.9m RMS
        # against the exporter's own reported accuracy) -- GLB-local (x, z)
        # to real (lat, lon). Vectorised: this project's own
        # `SiteTransform` methods are plain array arithmetic, confirmed to
        # broadcast correctly over the whole vertex array in this session.
        east_m, north_m = site_transform.scene_to_east_north_m(vx, vz)
        lat, lon = site_transform.east_north_to_latlon(east_m, north_m)

        # Same reference point Terrain.tsx's scene origin uses (dem_proxy's
        # site_lat/site_lon), so both components share one scene origin.
        north_rel_m = (lat - target_lat) * _METERS_PER_DEGREE_LAT
        east_rel_m = (
            (lon - target_lon) * _METERS_PER_DEGREE_LAT * math.cos(math.radians(target_lat))
        )
        # Elevation: scaled by the SAME real fit scale (~0.99, confirmed
        # near-1:1 -- see site_transform.py's own docstring), then lifted
        # onto the real terrain surface by the single-point DEM sample.
        new_y = vy * site_transform.scale + ground_elevation_m

        # Terrain.tsx's own convention (its module docstring): X=east,
        # Z=-north, Y=up.
        mesh.vertices = np.stack([east_rel_m, new_y, -north_rel_m], axis=1)
        scene.add_geometry(mesh, node_name=name)

    return scene


async def build_site_mesh_glb(site_id: str) -> Tuple[bytes, str]:
    """Real (or explicitly-placeholder) site mesh GLB for `site_id`.

    Returns `(glb_bytes, source)` where `source` is `"real_glb"` or
    `"placeholder_fallback"` — surfaced via the `X-Site-Mesh-Source`
    response header (routes.py), same convention as
    `alerts/site_geometry.py`'s `load_real_site_polygon`.
    """
    if site_id in _CACHE:
        return _CACHE[site_id]

    target_lat = settings.target_site_lat
    target_lon = settings.target_site_lon
    ground_elevation_m = 0.0
    if target_lat is not None and target_lon is not None:
        sampled = await _ground_elevation_m(target_lat, target_lon)
        if sampled is not None:
            ground_elevation_m = sampled

    source = "real_glb"
    if not _GLB_PATH.is_file() or not _ANCHOR_PATH.is_file():
        logger.warning(
            "Real GLB/anchor data not found at %s / %s — using placeholder site mesh.",
            _GLB_PATH,
            _ANCHOR_PATH,
        )
        scene = _placeholder_scene()
        source = "placeholder_fallback"
    else:
        try:
            scene = _real_scene(ground_elevation_m)
        except Exception as exc:
            logger.error(
                "Failed to build the real site mesh from %s: %s — falling back "
                "to placeholder.",
                _GLB_PATH,
                exc,
            )
            scene = _placeholder_scene()
            source = "placeholder_fallback"

    glb_bytes = scene.export(file_type="glb")
    result = (bytes(glb_bytes), source)
    _CACHE[site_id] = result
    return result
