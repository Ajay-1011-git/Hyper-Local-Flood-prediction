"""GLB ingestion — load the Blender-produced site model (T2.1).

API CONFIRMED IN-SESSION (anti-hallucination rule, not recalled from memory)
-----------------------------------------------------------------------------
Verified directly against the installed `trimesh` 5.0.0 by round-tripping a
real GLB in this session (build a `trimesh.Scene` with named boxes, export
to GLB bytes, reload, inspect):

    scene = trimesh.load(file_obj, file_type="glb", force="scene")
    # -> trimesh.scene.scene.Scene
    scene.geometry            # dict[str, trimesh.Trimesh], keyed by the
                               # object's name exactly as authored in Blender
    scene.graph.nodes_geometry  # list of scene-graph node names with geometry
    mesh.vertices, mesh.faces   # numpy arrays on each trimesh.Trimesh

`force="scene"` matters: without it, `trimesh.load` on a GLB with multiple
named objects can return a single merged `Trimesh` instead of a `Scene`,
losing the per-object names this task needs to match against
(`Building_01` etc.) — confirmed this in-session too (default `force=None`
merges; `force="scene"` preserves the scene graph).

EXACT NAMES REQUIRED (CLAUDE.md ground truth — no fuzzy matching)
---------------------------------------------------------------------
`Building_01`, `Building_02`, `Building_03`, `Road_Network`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import trimesh

from stage2.ingestion.errors import InvalidAnchorPointError, MissingSceneObjectError
from stage2.shared.contracts import AnchorPoint

REQUIRED_OBJECT_NAMES = ("Building_01", "Building_02", "Building_03", "Road_Network")


def _load_anchor_point(anchor_json_path: Path) -> AnchorPoint:
    """Parse and validate `anchor_point.json`.

    Raises:
        InvalidAnchorPointError: if the file is missing, not valid JSON, or
            fails `AnchorPoint`'s schema validation. Never returns a
            default/placeholder anchor.
    """
    if not anchor_json_path.is_file():
        raise InvalidAnchorPointError(
            f"No anchor point file at {anchor_json_path}. This must come "
            "from the Blender MCP deliverable, not be assumed."
        )
    try:
        raw = json.loads(anchor_json_path.read_text())
    except json.JSONDecodeError as exc:
        raise InvalidAnchorPointError(
            f"{anchor_json_path} is not valid JSON: {exc}"
        ) from exc
    try:
        return AnchorPoint.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError, kept generic on purpose
        raise InvalidAnchorPointError(
            f"{anchor_json_path} does not match the AnchorPoint contract: {exc}"
        ) from exc


def load_site_model(
    glb_path: str | Path, anchor_json_path: str | Path
) -> tuple[Dict[str, trimesh.Trimesh], AnchorPoint]:
    """Load the site GLB and anchor point.

    Returns a dict keyed by the exact required object names, mapped to
    each object's raw `trimesh.Trimesh` geometry (vertices/faces and
    everything else trimesh carries), and the parsed `AnchorPoint`.

    Raises:
        MissingSceneObjectError: if any of `REQUIRED_OBJECT_NAMES` is not
            present in the GLB. Never proceeds with a partial building set.
        InvalidAnchorPointError: if the anchor point file is missing or
            invalid.
    """
    glb_path = Path(glb_path)
    if not glb_path.is_file():
        raise MissingSceneObjectError(
            f"No GLB file at {glb_path}. This must be Blender MCP's finished "
            "deliverable, not be assumed to exist."
        )

    anchor = _load_anchor_point(Path(anchor_json_path))

    scene = trimesh.load(str(glb_path), file_type="glb", force="scene")
    if not isinstance(scene, trimesh.Scene):
        raise MissingSceneObjectError(
            f"{glb_path} loaded as a single merged mesh, not a multi-object "
            "scene — trimesh.load(..., force='scene') did not preserve "
            "per-object names. Cannot match against required object names."
        )

    missing = [name for name in REQUIRED_OBJECT_NAMES if name not in scene.geometry]
    if missing:
        raise MissingSceneObjectError(
            f"{glb_path} is missing required object(s): {missing}. Found: "
            f"{sorted(scene.geometry.keys())}. Not proceeding with a partial "
            "building set."
        )

    objects: Dict[str, trimesh.Trimesh] = {
        name: scene.geometry[name] for name in REQUIRED_OBJECT_NAMES
    }
    return objects, anchor
