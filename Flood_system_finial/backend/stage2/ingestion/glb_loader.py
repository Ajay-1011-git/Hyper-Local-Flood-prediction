"""GLB ingestion — load the Blender-produced site model (T2.1, amended 2026-08-20).

REAL DATA ARRIVED; TWO CONFIRMED CHANGES FROM THE ORIGINAL DESIGN
---------------------------------------------------------------------
1. **`Building_03` was removed from the design** (confirmed directly with
   the project owner, 2026-08-20) — replaced with garden/lawn/road/
   sidewalk assets. `REQUIRED_OBJECT_NAMES` no longer includes it.
2. **Objects are fragmented into multiple named pieces**, not one piece
   per object — an artifact of the real export pipeline's simplify step
   (`export_state.pipeline_used`: "dedup -> weld -> simplify -> prune").
   Confirmed by listing every real scene node: `Building_01` is 5 pieces
   (`Building_01_1e1d4b`, `Building_01_3a57cb`, ...), `Building_02` is 8,
   `Road_Network` is 4 — each sharing the base name as a prefix. This is
   the real, intended semantics (`anchor_point.json` itself cites "vertex
   on Building_01" for a point on one specific fragment), not ambiguous
   geometry — matched here by prefix and merged into one logical mesh per
   required object, in real WORLD coordinates (each piece's own transform
   applied before merging — confirmed necessary: `trimesh.Scene.graph`
   stores each node's transform relative to its parent, not the scene
   root, verified by comparing a loaded anchor node's world position
   against `anchor_point.json`'s own real values).

API CONFIRMED IN-SESSION (trimesh 5.0.0) — unchanged from before
-----------------------------------------------------------------------
    scene = trimesh.load(file_obj, file_type="glb", force="scene")
    scene.geometry            # dict[str, trimesh.Trimesh]
    scene.graph.nodes_geometry  # scene-graph node names with geometry
    scene.graph[node_name]      # -> (world_transform_4x4, geometry_name)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import trimesh

from stage2.ingestion.errors import MissingSceneObjectError
from stage2.terrain.site_transform import InvalidAnchorPointError, SiteTransform, fit_site_transform

REQUIRED_OBJECT_NAMES = ("Building_01", "Building_02", "Road_Network")


def _matching_node_names(scene: trimesh.Scene, base_name: str) -> List[str]:
    """Every scene-graph node that IS `base_name` or a fragment of it.

    A fragment's real node name is `f"{base_name}_{hash}"` — confirmed by
    inspecting the real GLB's actual node names (see module docstring).
    Matched by prefix, not fuzzy/substring, so e.g. `Building_01` never
    accidentally matches `Building_012` (not a real case here, but the
    distinction is real: CLAUDE.md rule "do not fuzzy-match or guess").
    """
    prefix = base_name + "_"
    return [
        name
        for name in scene.graph.nodes_geometry
        if name == base_name or name.startswith(prefix)
    ]


def _merged_world_mesh(scene: trimesh.Scene, node_names: List[str]) -> trimesh.Trimesh:
    """Concatenate every named piece's geometry, each in real WORLD coordinates.

    `scene.graph[name]` returns `(transform, geometry_name)` where
    `transform` is the node's full transform to the scene root — applying
    it before merging is what makes the combined mesh's vertices
    real/comparable across pieces (confirmed necessary: without it,
    pieces under different parent groups would be in incompatible local
    frames — see the anchor-node verification in `site_transform.py`).
    """
    pieces = []
    for name in node_names:
        transform, geom_name = scene.graph[name]
        mesh = scene.geometry[geom_name].copy()
        mesh.apply_transform(transform)
        pieces.append(mesh)
    if len(pieces) == 1:
        result: trimesh.Trimesh = pieces[0]
        return result
    merged = trimesh.util.concatenate(pieces)
    assert isinstance(merged, trimesh.Trimesh)
    return merged


def load_site_model(
    glb_path: str | Path, anchor_json_path: str | Path
) -> tuple[Dict[str, trimesh.Trimesh], SiteTransform]:
    """Load the site GLB and fit the real site georeferencing transform.

    Returns a dict keyed by `REQUIRED_OBJECT_NAMES`, each mapped to that
    object's merged, world-coordinate `trimesh.Trimesh` (all of its real
    fragments combined), and the fitted `SiteTransform` (see
    `terrain/site_transform.py` — an 18-point least-squares similarity
    fit, not a single-anchor-plus-axis-label).

    Raises:
        MissingSceneObjectError: if any of `REQUIRED_OBJECT_NAMES` has no
            matching fragment in the GLB. Never proceeds with a partial
            building set.
        InvalidAnchorPointError: if the anchor point file is missing,
            invalid, or has too few real anchors to fit.
    """
    glb_path = Path(glb_path)
    if not glb_path.is_file():
        raise MissingSceneObjectError(
            f"No GLB file at {glb_path}. This must be Blender MCP's finished "
            "deliverable, not be assumed to exist."
        )

    site_transform = fit_site_transform(anchor_json_path)

    scene = trimesh.load(str(glb_path), file_type="glb", force="scene")
    if not isinstance(scene, trimesh.Scene):
        raise MissingSceneObjectError(
            f"{glb_path} loaded as a single merged mesh, not a multi-object "
            "scene — trimesh.load(..., force='scene') did not preserve "
            "per-object names. Cannot match against required object names."
        )

    objects: Dict[str, trimesh.Trimesh] = {}
    missing: List[str] = []
    for base_name in REQUIRED_OBJECT_NAMES:
        node_names = _matching_node_names(scene, base_name)
        if not node_names:
            missing.append(base_name)
            continue
        objects[base_name] = _merged_world_mesh(scene, node_names)

    if missing:
        raise MissingSceneObjectError(
            f"{glb_path} is missing required object(s): {missing} (no scene "
            f"node named exactly this or with this as a name-prefix). "
            f"Found nodes: {sorted(scene.graph.nodes_geometry)}. Not "
            "proceeding with a partial building set."
        )

    return objects, site_transform
