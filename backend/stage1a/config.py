"""Stage 1A configuration — loads every variable declared in §B.1.

API note (anti-hallucination rule 2): the pydantic-settings interface used
here was confirmed against the installed package in-session, not recalled
from memory. `pydantic_settings.VERSION` == 2.15.0; `BaseSettings` and
`SettingsConfigDict` are both exported at the package root, and
`SettingsConfigDict` accepts the `env_file`, `env_file_encoding`,
`env_ignore_empty`, `case_sensitive`, and `extra` keys used below.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

MODULE_ROOT: Path = Path(__file__).resolve().parent


class Stage1ASettings(BaseSettings):
    """Every environment variable in §B.1, and nothing else.

    Blank values in `.env` are treated as "not set" (`env_ignore_empty`),
    so an unfilled `.env.example` field falls through to the default here
    rather than validating as an empty string.
    """

    # ---- GenCast (regional ensemble weather forecast) ----
    gencast_weights_path: Optional[str] = None
    gencast_tpu_endpoint: Optional[str] = None
    gencast_precomputed_fallback_dir: Path = MODULE_ROOT / "data" / "gencast_precomputed"

    # ---- CWC / India-WRIS (river & reservoir stage forecast) ----
    # Left as None by default on purpose: T1A.6 must confirm the real base
    # URLs against live documentation before anything is hardcoded here.
    cwc_data_portal_base_url: Optional[str] = None
    india_wris_base_url: Optional[str] = None

    # ---- Storage ----
    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"

    # ---- Target site (for river-stage nearest-station lookup) ----
    target_site_lat: Optional[float] = None
    target_site_lon: Optional[float] = None

    model_config = SettingsConfigDict(
        env_file=MODULE_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Stage1ASettings:
    """Return the process-wide settings singleton."""
    return Stage1ASettings()
