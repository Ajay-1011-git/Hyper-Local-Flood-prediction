"""Tests for Stage 2 settings loading (T2.0)."""

from __future__ import annotations

from pathlib import Path

from stage2.config import MODULE_ROOT, Stage2Settings, get_settings


def test_relative_glb_path_is_anchored_to_module_root() -> None:
    settings = Stage2Settings(site_glb_path=Path("./blender_prep/output/site.glb"))
    assert settings.site_glb_path.is_absolute()
    assert settings.site_glb_path == MODULE_ROOT / "blender_prep" / "output" / "site.glb"


def test_absolute_glb_path_is_left_alone() -> None:
    settings = Stage2Settings(site_glb_path=Path("/tmp/elsewhere.glb"))
    assert settings.site_glb_path == Path("/tmp/elsewhere.glb")


def test_inline_env_comment_falls_through_to_default() -> None:
    """Mirrors the real bug found/fixed in Stage 1A's config.py."""
    settings = Stage2Settings(
        mswe_gnn_pretrained_path="# path to pretrained weights if found"
    )
    assert settings.mswe_gnn_pretrained_path is None


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
