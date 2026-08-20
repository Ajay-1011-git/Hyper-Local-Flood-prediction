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

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def supported_languages_list(self) -> list[str]:
        return [lang.strip() for lang in self.supported_languages.split(",") if lang.strip()]


settings = Settings()
