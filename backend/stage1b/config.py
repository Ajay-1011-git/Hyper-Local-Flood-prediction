"""Stage 1B configuration, loaded from environment variables / `.env`.

Implements T1B.0. Uses `pydantic-settings` (verified installed version:
2.15.0) — `BaseSettings` with a `model_config = SettingsConfigDict(...)`
class attribute is the current (pydantic-settings v2) API; the old
pydantic v1-style inner `class Config:` is not used here.
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Bhuvan / NRSC (DEM) ----
    bhuvan_access_method: Optional[str] = None
    bhuvan_dem_product: str = "CartoDEM"

    # ---- TN WRD (rainfall calibration) ----
    tnwrd_dataset_url: str = (
        "https://nwdp.nwic.gov.in/dataset/rainfall-telemetry-hourly-tamil-nadu-sw-gw"
    )

    # ---- Storage ----
    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"
    dem_raster_storage_dir: str = "./data/dem"

    # ---- Target site ----
    target_site_id: str = "vellore_demo_site_01"
    target_site_lat: Optional[float] = None
    target_site_lon: Optional[float] = None

    # ---- Sensor ingestion ----
    sensor_ingest_token: Optional[str] = None


settings = Settings()
