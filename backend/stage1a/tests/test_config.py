"""Tests for Stage 1A settings loading (T1A.0)."""

from __future__ import annotations

from pathlib import Path

from stage1a.config import MODULE_ROOT, Stage1ASettings, get_settings


def test_relative_wn2_path_is_anchored_to_module_root() -> None:
    settings = Stage1ASettings(
        wn2_mini_forecast_path=Path("./data/wn2_mini/tn_flood_forecast.nc")
    )
    assert settings.wn2_mini_forecast_path.is_absolute()
    assert settings.wn2_mini_forecast_path == (
        MODULE_ROOT / "data" / "wn2_mini" / "tn_flood_forecast.nc"
    )


def test_absolute_wn2_path_is_left_alone() -> None:
    settings = Stage1ASettings(wn2_mini_forecast_path=Path("/tmp/elsewhere.nc"))
    assert settings.wn2_mini_forecast_path == Path("/tmp/elsewhere.nc")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
