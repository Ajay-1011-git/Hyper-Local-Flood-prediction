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
    """Write a real GLB with the 4 required named objects, arbitrary geometry."""
    scene = trimesh.Scene()
    extents = {
        "Building_01": [8.0, 6.0, 12.0],
        "Building_02": [10.0, 10.0, 9.0],
        "Building_03": [6.0, 6.0, 15.0],
        "Road_Network": [40.0, 4.0, 0.2],
    }
    for name in REQUIRED_OBJECT_NAMES:
        box = trimesh.creation.box(extents=extents[name])
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
