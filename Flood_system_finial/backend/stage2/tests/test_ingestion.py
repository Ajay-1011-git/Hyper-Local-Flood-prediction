"""Tests for GLB ingestion (T2.1, amended 2026-08-20 for real data/SiteTransform)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stage2.ingestion.glb_loader import REQUIRED_OBJECT_NAMES, load_site_model
from stage2.ingestion.errors import MissingSceneObjectError
from stage2.terrain.site_transform import InvalidAnchorPointError
from stage2.tests.fixtures import write_synthetic_anchor_point, write_synthetic_site_glb


def test_loads_all_required_objects_with_real_geometry(tmp_path: Path) -> None:
    glb_path = tmp_path / "site.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_site_glb(glb_path)
    write_synthetic_anchor_point(anchor_path)

    objects, site_transform = load_site_model(glb_path, anchor_path)

    assert set(objects.keys()) == set(REQUIRED_OBJECT_NAMES)
    for name, mesh in objects.items():
        assert len(mesh.vertices) > 0
        assert len(mesh.faces) > 0
    assert site_transform.ref_lat == pytest.approx(12.9165, abs=0.01)
    assert site_transform.rms_residual_m >= 0.0


def test_fragmented_objects_are_merged_by_name_prefix(tmp_path: Path) -> None:
    """Real buildings are 5-8 hash-suffixed pieces per object (e.g.
    `Building_01_1e1d4b`), not one piece exactly named `Building_01` --
    confirmed against the real GLB's actual scene graph. This exercises
    that prefix-matching/merge logic directly."""
    glb_path = tmp_path / "fragmented.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_site_glb(glb_path, fragmented=True)
    write_synthetic_anchor_point(anchor_path)

    objects, _ = load_site_model(glb_path, anchor_path)

    assert set(objects.keys()) == set(REQUIRED_OBJECT_NAMES)
    for mesh in objects.values():
        assert len(mesh.vertices) > 0


def test_missing_glb_file_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(MissingSceneObjectError):
        load_site_model(tmp_path / "nonexistent.glb", tmp_path / "anchor.json")


def test_missing_anchor_file_raises_typed_error(tmp_path: Path) -> None:
    glb_path = tmp_path / "site.glb"
    write_synthetic_site_glb(glb_path)
    with pytest.raises(InvalidAnchorPointError):
        load_site_model(glb_path, tmp_path / "nonexistent_anchor.json")


def test_invalid_anchor_json_raises_typed_error(tmp_path: Path) -> None:
    glb_path = tmp_path / "site.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_site_glb(glb_path)
    anchor_path.write_text("{not valid json")
    with pytest.raises(InvalidAnchorPointError):
        load_site_model(glb_path, anchor_path)


def test_anchor_missing_required_field_raises_typed_error(tmp_path: Path) -> None:
    glb_path = tmp_path / "site.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_site_glb(glb_path)
    anchor_path.write_text('{"primary": {"scene_object_name": "Anchor"}}')  # missing required fields
    with pytest.raises(InvalidAnchorPointError):
        load_site_model(glb_path, anchor_path)


def test_single_anchor_is_insufficient_for_a_fit(tmp_path: Path) -> None:
    """A similarity fit needs >=2 real anchors to solve scale+rotation."""
    glb_path = tmp_path / "site.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_site_glb(glb_path)
    write_synthetic_anchor_point(anchor_path, num_extra_anchors=0)
    with pytest.raises(InvalidAnchorPointError):
        load_site_model(glb_path, anchor_path)


def test_missing_scene_object_raises_typed_error_naming_it(tmp_path: Path) -> None:
    import trimesh

    glb_path = tmp_path / "incomplete.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_anchor_point(anchor_path)

    scene = trimesh.Scene()
    # Only 2 of the 3 required objects -- Road_Network deliberately omitted.
    for name in ["Building_01", "Building_02"]:
        scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name=name, node_name=name)
    glb_path.write_bytes(scene.export(file_type="glb"))

    with pytest.raises(MissingSceneObjectError, match="Road_Network"):
        load_site_model(glb_path, anchor_path)


def test_single_merged_mesh_without_names_is_rejected(tmp_path: Path) -> None:
    """A GLB with no scene graph (one merged mesh) can't be matched by name."""
    import trimesh

    glb_path = tmp_path / "merged.glb"
    anchor_path = tmp_path / "anchor_point.json"
    write_synthetic_anchor_point(anchor_path)

    mesh = trimesh.creation.box(extents=[1, 1, 1])
    glb_path.write_bytes(mesh.export(file_type="glb"))

    with pytest.raises(MissingSceneObjectError):
        load_site_model(glb_path, anchor_path)
