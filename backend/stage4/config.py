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

    # Confirmed and filled in during T4A.1 once the real CAP/SACHET schema
    # is looked up in-session -- left blank (not guessed) until then, per
    # this project's anti-hallucination discipline.
    sachet_schema_version: Optional[str] = None

    # English + Tamil at minimum, per PRD NFR-6. A plain comma-separated
    # string (not a list) so it round-trips through .env without needing
    # pydantic-settings' JSON-list parsing convention.
    supported_languages: str = "en,ta"

    @property
    def supported_languages_list(self) -> list[str]:
        return [lang.strip() for lang in self.supported_languages.split(",") if lang.strip()]


settings = Settings()
