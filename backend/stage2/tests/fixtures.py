"""Synthetic, GLB-SHAPED fixtures for tests.

IMPORTANT: nothing here is the real VIT Vellore site model. These builders
produce a real, valid GLB file (round-tripped through trimesh's real
export/load, not hand-crafted bytes) with the required object names and
arbitrary box geometry, purely so T2.1's loader logic can be exercised
without the actual Blender MCP deliverable. Must never be presented as, or
substituted for, the real site model.
"""

from __future__ import annotations

import json
from pathlib import Path

import trimesh

from stage2.ingestion.glb_loader import REQUIRED_OBJECT_NAMES


def write_synthetic_site_glb(path: Path) -> None:
    """Write a real GLB with the 4 required named objects, arbitrary geometry.

    Objects are translated to distinct, non-overlapping ground positions
    (a small arbitrary campus-like layout) — `trimesh.creation.box`
    centers each box at the origin by default, and an earlier version of
    this fixture left every object stacked on top of the others, which a
    real T2.4 integration run caught (DoubleTaggedNodeError) even though
    each per-building unit test passed in isolation.
    """
    scene = trimesh.Scene()
    extents = {
        "Building_01": [8.0, 6.0, 12.0],
        "Building_02": [10.0, 10.0, 9.0],
        "Building_03": [6.0, 6.0, 15.0],
        "Road_Network": [40.0, 4.0, 0.2],
    }
    translations = {
        "Building_01": [-15.0, -10.0, 0.0],
        "Building_02": [10.0, 5.0, 0.0],
        "Building_03": [-10.0, 12.0, 0.0],
        "Road_Network": [0.0, -20.0, 0.0],
    }
    for name in REQUIRED_OBJECT_NAMES:
        box = trimesh.creation.box(extents=extents[name])
        box.apply_translation(translations[name])
        scene.add_geometry(box, geom_name=name, node_name=name)
    path.write_bytes(scene.export(file_type="glb"))


def write_synthetic_anchor_point(path: Path) -> None:
    """Write a real, schema-valid anchor_point.json with arbitrary values."""
    anchor = {
        "scene_object_name": "Anchor",
        "scene_local_position": [0.0, 0.0, 0.0],
        "real_world_lat": 12.9165,
        "real_world_lon": 79.1325,
        "real_world_elevation_m": 216.0,
        "scene_to_real_scale_factor": 1.0,
        "north_axis": "+Y",
    }
    path.write_text(json.dumps(anchor))


def write_synthetic_terrain_geotiff(path: Path, resolution_m: float = 5.0, size: int = 20) -> None:
    """Write a real, valid 3-band GeoTIFF matching Stage 1B's format.

    Band order/meaning mirrors `backend/stage1b/dem/processing.py`'s
    `write_terrain_grids_geotiff` exactly (1=elevation, 2=slope_deg,
    3=aspect_deg), in a real projected UTM CRS (zone 44N, correct for
    Vellore's ~79 deg E longitude) — NOT the real Vellore terrain, an
    arbitrary sloped surface, clearly a synthetic fixture.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    # Arbitrary UTM 44N origin roughly matching Vellore's real coordinates,
    # so the fixture's bbox is physically plausible for round-trip tests.
    west, north = 300_000.0, 1_430_000.0
    transform = from_origin(west, north, resolution_m, resolution_m)

    y, x = np.mgrid[0:size, 0:size]
    elevation = (200.0 + 0.5 * x + 0.3 * y).astype(np.float32)  # a simple synthetic slope
    slope = np.full((size, size), 5.0, dtype=np.float32)
    aspect = np.full((size, size), 45.0, dtype=np.float32)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=3,
        dtype="float32",
        crs="EPSG:32644",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(elevation, 1)
        dst.write(slope, 2)
        dst.write(aspect, 3)
