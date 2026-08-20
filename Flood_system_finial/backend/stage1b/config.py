"""Stage 1B configuration, loaded from environment variables / `.env`.

Implements T1B.0. Uses `pydantic-settings` (verified installed version:
2.15.0) — `BaseSettings` with a `model_config = SettingsConfigDict(...)`
class attribute is the current (pydantic-settings v2) API; the old
pydantic v1-style inner `class Config:` is not used here.
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file, not the process's cwd — a bare ".env"
# only loads when the process happens to be launched from
# backend/stage1b/, which is not how tests/scripts here are actually run
# (from the repo root). This fixes that regardless of invocation directory.
_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Bhuvan / NRSC (DEM) ----
    # Confirmed in T1B.2 (see dem/client.py's module docstring for sources
    # consulted): Bhuvan's legacy portal has no scriptable DEM download path
    # (WMS/WMTS = map tiles only; the actual raster is behind a login-gated
    # manual browser flow). The real, current, scriptable access path is
    # NRSC's Bhoonidhi geoportal REST API (bhoonidhi-api.nrsc.gov.in).
    bhuvan_access_method: str = "bhoonidhi_api"
    bhuvan_dem_product: str = "CartoDEM"
    bhoonidhi_base_url: str = "https://bhoonidhi-api.nrsc.gov.in"
    bhoonidhi_user_id: Optional[str] = None
    bhoonidhi_password: Optional[str] = None
    # Confirmed collection id for CartoDEM (from GET /data/collections);
    # kept overridable in case NRSC renames/versions it.
    bhoonidhi_dem_collection: str = "CartoSat-1_PAN_CartoDEM_30m"

    # ---- TN WRD (rainfall calibration) ----
    tnwrd_dataset_url: str = (
        "https://nwdp.nwic.gov.in/dataset/rainfall-telemetry-hourly-tamil-nadu-sw-gw"
    )

    # ---- Storage ----
    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"
    dem_raster_storage_dir: str = "./data/dem"

    # ---- Target site ----
    # 2026-08-20: standardized to "vit-vellore" and the real GLB-surveyed
    # anchor coordinates (anchor_point.json's "primary" anchor, T4 unified
    # fit -- backend/stage2/blender_prep/output/anchor_point.json) across
    # all four stages, per explicit project-owner decision during a
    # full-system wiring audit. Previously "vellore_demo_site_01" /
    # (12.9165, 79.1325) -- a placeholder site_id and a stale coordinate
    # ~6km from the real site, predating the real 3D model (flagged by
    # Stage 2's own session in stage1b/CLAUDE.md's addendum, left for
    # this module's owner to decide -- this is that decision).
    target_site_id: str = "vit-vellore"
    target_site_lat: Optional[float] = 12.969223
    target_site_lon: Optional[float] = 79.155934

    # ---- Sensor ingestion ----
    sensor_ingest_token: Optional[str] = None

    # ---- Stage 1A integration (T1B.9) ----
    # Unset by default: Stage 1A has no live endpoint in this repo yet
    # (built independently). When unset, routes.py falls back to an
    # explicitly-labeled mock RegionalEnsembleForecast fixture — see its
    # module docstring.
    stage1a_regional_forecast_url: Optional[str] = None


settings = Settings()
