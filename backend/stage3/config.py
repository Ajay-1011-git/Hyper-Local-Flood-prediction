"""Stage 3 configuration, loaded from environment variables / `.env`.

Implements T3.0. Mirrors Stage 1B's config.py pattern (pydantic-settings,
current `SettingsConfigDict` API, .env resolved relative to this file's
own location rather than the process's cwd).
"""

from pathlib import Path
from typing import Optional

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

    # T3.6: Stage 2's real, documented endpoint is `GET /api/simulation/
    # site/{site_id}` (stage2 build doc T2.9) -- this is the BASE url
    # (no trailing site_id), matching Stage 1B's STAGE1A_REGIONAL_
    # FORECAST_URL pattern for the same "no live upstream in this repo
    # yet" situation. None until Ajay's Stage 2 has a running deployment
    # to point at; routes.py falls back to an explicitly-labeled mock
    # fixture when unset (or on fetch failure), same as Stage 1B did for
    # Stage 1A before it went live.
    stage2_simulation_result_base_url: Optional[str] = None

    # Flagged per this project's convention for unverified defaults: no
    # doc states how long a SimulationResult / its derived DamageRankEntry
    # ranking should be considered fresh. A reasonable starting point
    # (matches Stage 1B's forecast-window order of magnitude), not an
    # independently proven-correct value -- revisit once Stage 2 states
    # its own real simulation-refresh cadence.
    damage_ranking_cache_ttl_seconds: int = 3600


settings = Settings()
