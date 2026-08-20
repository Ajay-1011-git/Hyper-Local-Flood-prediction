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
from typing import TYPE_CHECKING

import trimesh

from stage2.ingestion.glb_loader import REQUIRED_OBJECT_NAMES

if TYPE_CHECKING:
    from stage2.terrain.site_transform import SiteTransform


def write_synthetic_site_glb(path: Path, fragmented: bool = False) -> None:
    """Write a real GLB with the required named objects, arbitrary geometry.

    Ground plane is (X, Z) -- glTF Y-up, matching the real confirmed
    convention (see `terrain/site_transform.py`'s docstring). Objects are
    translated to distinct, non-overlapping ground positions (a small
    arbitrary campus-like layout) — `trimesh.creation.box` centers each
    box at the origin by default, and an earlier version of this fixture
    left every object stacked on top of the others, which a real T2.4
    integration run caught (DoubleTaggedNodeError) even though each
    per-building unit test passed in isolation.

    `fragmented=True` splits each required object into 2 separately-named
    pieces sharing its name as a prefix (`Building_01_a`, `Building_01_b`),
    matching the real GLB's actual shape (confirmed: real buildings are
    5-8 fragments each, an artifact of the export pipeline's simplify
    step) — for tests of T2.1's prefix-matching/merge logic specifically.
    """
    scene = trimesh.Scene()
    extents = {
        "Building_01": [8.0, 12.0, 6.0],
        "Building_02": [10.0, 9.0, 10.0],
        "Road_Network": [40.0, 0.2, 4.0],
    }
    translations = {
        "Building_01": [-15.0, 0.0, -10.0],
        "Building_02": [10.0, 0.0, 5.0],
        "Road_Network": [0.0, 0.0, -20.0],
    }
    for name in REQUIRED_OBJECT_NAMES:
        ex = extents[name]
        tr = translations[name]
        if not fragmented:
            box = trimesh.creation.box(extents=ex)
            box.apply_translation(tr)
            scene.add_geometry(box, geom_name=name, node_name=name)
        else:
            half = ex[0] / 2.0
            for i, x_offset in enumerate((-half / 2.0, half / 2.0)):
                piece = trimesh.creation.box(extents=[ex[0] / 2.0, ex[1], ex[2]])
                piece.apply_translation([tr[0] + x_offset, tr[1], tr[2]])
                piece_name = f"{name}_{i}"
                scene.add_geometry(piece, geom_name=piece_name, node_name=piece_name)
    path.write_bytes(scene.export(file_type="glb"))


def write_synthetic_anchor_point(path: Path, num_extra_anchors: int = 5) -> None:
    """Write a real, schema-valid anchor_point.json matching the REAL confirmed
    structure (primary + additional_anchors, gltf_yup positions, real
    lat/lon) -- not the old flat single-point shape.

    Uses an identity-like transform (scale=1, no rotation) so
    `fit_site_transform` recovers exactly `ref_lat`/`ref_lon` at the
    origin, useful for tests that want predictable coordinates.
    """
    ref_lat, ref_lon = 12.9165, 79.1325
    m_per_deg_lat = 111_320.0

    def offset_anchor(name: str, east_m: float, north_m: float) -> dict:
        lat = ref_lat + north_m / m_per_deg_lat
        import math

        lon = ref_lon + east_m / (m_per_deg_lat * math.cos(math.radians(ref_lat)))
        return {
            "scene_object_name": name,
            "gltf_yup_position": [east_m, 0.0, -north_m],  # East=X, North=-Z convention
            "real_world_lat": lat,
            "real_world_lon": lon,
        }

    primary = offset_anchor("Anchor_Primary", 0.0, 0.0)
    doc = {
        "primary": {
            "scene_object_name": primary["scene_object_name"],
            "scene_local_position_gltf_yup": primary["gltf_yup_position"],
            "real_world_lat": primary["real_world_lat"],
            "real_world_lon": primary["real_world_lon"],
            "real_world_elevation_m": None,
            "scene_to_real_scale_factor": 1.0,
        },
        "additional_anchors": [
            offset_anchor(f"Anchor_Extra_{i}", float(i * 10 - 20), float(i * 7 - 15))
            for i in range(num_extra_anchors)
        ],
    }
    path.write_text(json.dumps(doc))


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


def synthetic_site_transform() -> "SiteTransform":
    """An identity-like SiteTransform for isolated unit tests (no anchor_point.json needed).

    scale=1, no rotation, centered at Vellore -- east/north == scene (x, -z)
    directly, so tests can reason about coordinates without going through
    a real least-squares fit.
    """
    from stage2.terrain.site_transform import SiteTransform as _SiteTransform

    return _SiteTransform(
        scale=1.0,
        rotation_matrix=((1.0, 0.0), (0.0, 1.0)),
        translation_m=(0.0, 0.0),
        ref_lat=12.9165,
        ref_lon=79.1325,
        rms_residual_m=0.0,
        per_anchor_residuals_m={},
    )
