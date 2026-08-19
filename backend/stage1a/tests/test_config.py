"""Tests for Stage 1A settings loading (T1A.0)."""

from __future__ import annotations

from pathlib import Path

from stage1a.config import MODULE_ROOT, Stage1ASettings, get_settings


def test_relative_fallback_dir_is_anchored_to_module_root() -> None:
    settings = Stage1ASettings(
        gencast_precomputed_fallback_dir=Path("./data/gencast_precomputed")
    )
    assert settings.gencast_precomputed_fallback_dir.is_absolute()
    assert settings.gencast_precomputed_fallback_dir == (
        MODULE_ROOT / "data" / "gencast_precomputed"
    )


def test_absolute_fallback_dir_is_left_alone() -> None:
    settings = Stage1ASettings(gencast_precomputed_fallback_dir=Path("/tmp/elsewhere"))
    assert settings.gencast_precomputed_fallback_dir == Path("/tmp/elsewhere")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
