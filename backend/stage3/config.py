"""Stage 3 configuration, loaded from environment variables / `.env`.

Implements T3.0. Mirrors Stage 1B's config.py pattern (pydantic-settings,
current `SettingsConfigDict` API, .env resolved relative to this file's
own location rather than the process's cwd).
"""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"

    # Flagged per this project's convention for unverified defaults (same
    # pattern as T1A.7/T1B.5's station-proximity threshold): a reasonable
    # starting point, not an independently proven-correct value.
    hazard_threshold_depth_m: float = 0.3

    # Filled in once T3.4 confirms a real, cited, published depth-damage
    # curve — must never be blank when vulnerability scoring actually runs.
    vulnerability_curve_source: Optional[str] = None


settings = Settings()
