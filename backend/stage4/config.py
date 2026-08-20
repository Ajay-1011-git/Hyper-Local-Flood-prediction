"""Stage 4 configuration, loaded from environment variables / `.env`.

Implements T4A.0. Mirrors Stage 2/3's config.py pattern (pydantic-settings,
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

    # Confirmed real (T4A.1): SACHET (NDMA/C-DOT's national CAP alerting
    # platform) uses plain, unmodified OASIS CAP 1.2 -- no SACHET-specific
    # schema variant or custom namespace, per a live web search + a
    # specific technical writeup quoting real SACHET CAP feed output.
    sachet_schema_version: Optional[str] = "1.2"

    # English + Tamil at minimum, per PRD NFR-6; Hindi/Telugu/Malayalam/
    # Kannada added 2026-08-20 per explicit project-owner request (all
    # real Sarvam-supported codes -- see sarvam_client.py). A plain
    # comma-separated string (not a list) so it round-trips through .env
    # without needing pydantic-settings' JSON-list parsing convention.
    supported_languages: str = "en,ta,hi,te,ml,kn"

    # T4A.2: Sarvam AI (real translation + text-to-speech), per explicit
    # project-owner decision (2026-08-20). Never given a default value --
    # a blank/missing key must fail loudly (SarvamNotConfiguredError), not
    # silently fall back to fabricated translated text.
    sarvam_api_key: Optional[str] = None

    # T4A.3: cross-stage sources for the alert route, mirroring Stage 3's
    # own STAGE2_SIMULATION_RESULT_BASE_URL pattern exactly (real base URL
    # if configured/reachable, explicitly-labeled mock fallback
    # otherwise -- never silently guessed).
    stage2_simulation_result_base_url: Optional[str] = None
    stage3_damage_ranking_base_url: Optional[str] = None
    alert_cache_ttl_seconds: int = 3600  # flagged, unverified-optimal default

    # T4B.0: real browser origins allowed to call this API. An explicit
    # allowlist, never "*" -- see routes.py's own CORS comment. Comma-
    # separated (same convention as supported_languages) so it round-trips
    # through .env without JSON-list parsing.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- T4B.3: terrain heightmap proxy ----
    # The real demo site. Defaults match the coordinates Stage 1B/2/3 all
    # use (12.9691, 79.1559 -- the real VIT Vellore site confirmed by the
    # GLB's own anchor-point fit), NOT Stage 1A's stale 12.9165/79.1325
    # placeholder.
    target_site_lat: Optional[float] = 12.969223
    target_site_lon: Optional[float] = 79.155934
    # Wide surrounding terrain: ~2km each way, decimated for frame rate
    # (TRD 6, point 3 -- decimate the surround, keep the site detailed).
    regional_terrain_half_span_m: float = 2000.0
    # 64 -> ~3x decimation of the ~30m source over 4km, so the surround is
    # genuinely lower-poly than the site patch (TRD 6 point 3). Set equal to
    # or above the native sample count and there is no decimation at all --
    # which is what an earlier 160 silently did.
    regional_terrain_max_dim: int = 64
    # Site-local patch: ~150m each way, rendered at the raster's NATIVE
    # resolution (no decimation). NOTE: the source is ~30m CartoDEM, so
    # "full resolution" is the raster's, not survey-grade -- that is only
    # ~10x10 real samples over this extent. See dem_proxy.py's docstring.
    site_terrain_half_span_m: float = 150.0

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def supported_languages_list(self) -> list[str]:
        return [lang.strip() for lang in self.supported_languages.split(",") if lang.strip()]


settings = Settings()
