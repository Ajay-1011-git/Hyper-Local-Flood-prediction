"""Stage 3 configuration, loaded from environment variables / `.env`.

Implements T3.0. Mirrors Stage 1B's config.py pattern (pydantic-settings,
current `SettingsConfigDict` API, .env resolved relative to this file's
own location rather than the process's cwd).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.stage3.vulnerability.fragility_curve import VULNERABILITY_CURVE_SOURCE

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

    # T3.4's real, cited, published depth-damage curve (see
    # vulnerability/fragility_curve.py's module docstring for the full
    # citation detail) -- defaults to it directly rather than staying
    # blank, since T3.4 is now done; still overridable via .env if a
    # human supplies a different confirmed source later.
    vulnerability_curve_source: str = VULNERABILITY_CURVE_SOURCE


settings = Settings()
