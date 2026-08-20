"""Stage 2 configuration — loads every variable declared in §B.1.

API note (anti-hallucination rule): pydantic-settings' interface was
already confirmed in-session for this project (Stage 1A's config.py,
pydantic_settings 2.15.0) — `BaseSettings`/`SettingsConfigDict` reused
identically here, not re-derived from memory.

Carries forward a real bug fix from Stage 1A: `.env.example`'s
`KEY=            # comment` pattern for unfilled fields is not treated as
empty by python-dotenv for an unquoted assignment — it keeps the comment
text as the literal value. See `_strip_inline_env_comments` below, ported
from `backend/stage1a/config.py` where this was found and fixed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MODULE_ROOT: Path = Path(__file__).resolve().parent


class Stage2Settings(BaseSettings):
    """Every environment variable in §B.1, and nothing else."""

    site_glb_path: Path = MODULE_ROOT / "blender_prep" / "output" / "vit_vellore_site.glb"
    site_anchor_json_path: Path = (
        MODULE_ROOT / "blender_prep" / "output" / "anchor_point.json"
    )
    dem_source: str = "stage1b"
    mswe_gnn_pretrained_path: Optional[str] = None
    terrain_grid_resolution_m: float = 1.0

    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"

    @model_validator(mode="before")
    @classmethod
    def _strip_inline_env_comments(cls, data: Any) -> Any:
        """Strip trailing `  # comment` text from string env values.

        See backend/stage1a/config.py's identical validator for the full
        explanation and the bug it was found fixing.
        """
        if not isinstance(data, dict):
            return data
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                candidate = value.strip()
                if candidate.startswith("#"):
                    stripped = ""
                else:
                    stripped = re.sub(r"\s+#.*$", "", candidate).strip()
                if stripped:
                    cleaned[key] = stripped
            else:
                cleaned[key] = value
        return cleaned

    @field_validator("site_glb_path", "site_anchor_json_path", mode="after")
    @classmethod
    def _anchor_to_module_root(cls, value: Path) -> Path:
        """Resolve a relative path against the module root, not the CWD.

        Same real bug as Stage 1A's fallback-dir path: a relative path
        resolves differently depending on where the process is launched
        from (API server vs. Celery worker vs. pytest).
        """
        return value if value.is_absolute() else (MODULE_ROOT / value).resolve()

    model_config = SettingsConfigDict(
        env_file=MODULE_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Stage2Settings:
    """Return the process-wide settings singleton."""
    return Stage2Settings()
