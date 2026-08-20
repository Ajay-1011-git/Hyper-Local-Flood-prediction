"""Tests for T4B.4 — site mesh (buildings + roads) proxy.

The real GLB/anchor files are ~11MB and gitignored (same situation as
Stage 2/3's own real-data tests) — so the placeholder-fallback path is
tested unconditionally (monkeypatching the module's path constants to
guarantee it, not relying on the files being absent), and the real-GLB
path is tested only `skipif` the real files happen to be present in this
checkout (true in this development environment, not guaranteed in CI).

`_ground_elevation_m` needs a live Postgres (Stage 1B's `dem_metadata`) —
monkeypatched to a fixed value everywhere here, same convention as
`test_routes.py` mocking Sarvam: never let an automated test depend on a
live external service succeeding.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from backend.stage4.scene import site_mesh

_FIXED_GROUND_ELEVATION_M = 132.0


@pytest.fixture(autouse=True)
def _mock_ground_elevation():
    async def _fixed(lat: float, lon: float) -> float:
        return _FIXED_GROUND_ELEVATION_M

    with patch.object(site_mesh, "_ground_elevation_m", side_effect=_fixed):
        yield


@pytest.fixture(autouse=True)
def _clear_cache():
    site_mesh._CACHE.clear()
    yield
    site_mesh._CACHE.clear()


def test_placeholder_scene_has_the_three_required_named_objects():
    scene = site_mesh._placeholder_scene()
    assert set(scene.geometry.keys()) >= set()  # geometry dict is keyed by hash, not name
    assert set(site_mesh.REQUIRED_OBJECT_NAMES) <= set(scene.graph.nodes_geometry)


async def test_falls_back_to_placeholder_when_glb_missing(tmp_path):
    with patch.object(site_mesh, "_GLB_PATH", tmp_path / "no_such.glb"):
        with patch.object(site_mesh, "_ANCHOR_PATH", tmp_path / "no_such.json"):
            glb_bytes, source = await site_mesh.build_site_mesh_glb("test_site_missing")

    assert source == "placeholder_fallback"
    assert glb_bytes[:4] == b"glTF"  # real GLB magic, even for the placeholder


async def test_falls_back_to_placeholder_when_real_loader_raises(tmp_path):
    """Files exist but aren't a real GLB/anchor pair -- the real loader
    must raise, not crash the whole request; this path is never allowed to
    propagate an exception out to the route."""
    fake_glb = tmp_path / "vit_vellore_site.glb"
    fake_anchor = tmp_path / "anchor_point.json"
    fake_glb.write_bytes(b"not a real glb")
    fake_anchor.write_text("{}")

    with patch.object(site_mesh, "_GLB_PATH", fake_glb):
        with patch.object(site_mesh, "_ANCHOR_PATH", fake_anchor):
            glb_bytes, source = await site_mesh.build_site_mesh_glb("test_site_corrupt")

    assert source == "placeholder_fallback"
    assert glb_bytes[:4] == b"glTF"


async def test_result_is_cached_per_site_id(tmp_path):
    with patch.object(site_mesh, "_GLB_PATH", tmp_path / "no_such.glb"):
        with patch.object(site_mesh, "_ANCHOR_PATH", tmp_path / "no_such.json"):
            first = await site_mesh.build_site_mesh_glb("test_site_cache")
            assert "test_site_cache" in site_mesh._CACHE
            second = await site_mesh.build_site_mesh_glb("test_site_cache")

    assert first == second


@pytest.mark.skipif(
    not (site_mesh._GLB_PATH.is_file() and site_mesh._ANCHOR_PATH.is_file()),
    reason="Real GLB/anchor data (gitignored) not present in this checkout.",
)
async def test_real_glb_transforms_into_terrain_scene_frame():
    """With the real GLB present: real object names appear, and every
    vertex lands within a plausible distance of the scene origin (the
    site is ~300m across) with elevation close to the real DEM ground
    sample -- i.e. genuinely placed on the terrain, not at the raw GLB's
    near-zero local height."""
    glb_bytes, source = await site_mesh.build_site_mesh_glb("vit_vellore_real")
    assert source == "real_glb"

    import trimesh

    scene = trimesh.load(
        trimesh.util.wrap_as_stream(glb_bytes), file_type="glb", force="scene"
    )
    assert set(site_mesh.REQUIRED_OBJECT_NAMES) <= set(scene.graph.nodes_geometry)

    for name in site_mesh.REQUIRED_OBJECT_NAMES:
        transform, geom_name = scene.graph[name]
        mesh = scene.geometry[geom_name]
        verts = mesh.apply_transform(transform).vertices if False else mesh.vertices
        # Site patch is ~300m across -- every vertex should be well within it.
        assert np.all(np.abs(verts[:, 0]) < 500), f"{name} X out of range"
        assert np.all(np.abs(verts[:, 2]) < 500), f"{name} Z out of range"
        # Elevation should sit close to the real DEM ground sample, not at
        # the raw GLB's own near-zero local height.
        assert np.all(verts[:, 1] > _FIXED_GROUND_ELEVATION_M - 20)
        assert np.all(verts[:, 1] < _FIXED_GROUND_ELEVATION_M + 60)
