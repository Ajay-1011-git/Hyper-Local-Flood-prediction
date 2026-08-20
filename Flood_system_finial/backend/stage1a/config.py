"""Stage 1A configuration — loads every variable declared in §B.1.

API note (anti-hallucination rule 2): the pydantic-settings interface used
here was confirmed against the installed package in-session, not recalled
from memory. `pydantic_settings.VERSION` == 2.15.0; `BaseSettings` and
`SettingsConfigDict` are both exported at the package root, and
`SettingsConfigDict` accepts the `env_file`, `env_file_encoding`,
`env_ignore_empty`, `case_sensitive`, and `extra` keys used below.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MODULE_ROOT: Path = Path(__file__).resolve().parent


class Stage1ASettings(BaseSettings):
    """Every environment variable in §B.1, and nothing else.

    Blank values in `.env` are treated as "not set" (`env_ignore_empty`),
    so an unfilled `.env.example` field falls through to the default here
    rather than validating as an empty string.
    """

    # ---- GEFS (NOAA Global Ensemble Forecast System, 0.25deg) ----
    # 2026-08-20 amendment: GEFS is now the primary regional-forecast
    # source (confirmed live via NOAA's real NOMADS grib-filter service
    # this session -- see gefs/client.py's module docstring). Real,
    # confirmed, currently-live endpoint -- not assumed.
    # PRIMARY transport: NOAA's Open Data Dissemination S3 bucket. Chosen
    # over the NOMADS filter service after the latter demonstrably
    # rate-limited/load-shed this session under a real full-cycle fetch
    # (372 requests), silently costing GEFS the chain. S3 has no such
    # limit; the cost is bandwidth (the whole global 0.25deg APCP record
    # per member/hour, ~287KB, vs NOMADS's ~750-byte server-side subset)
    # -- confirmed live, see gefs/client.py's module docstring.
    gefs_s3_base_url: str = "https://noaa-gefs-pds.s3.amazonaws.com"
    # FALLBACK transport: NOMADS's GRIB-filter CGI (server-side subsetting).
    gefs_filter_base_url: str = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl"
    # NOAA typically publishes a cycle ~4-5h after its nominal time;
    # requesting too soon gets a real "not yet published" error (confirmed
    # live: a future/unpublished cycle returns HTTP 403 with NOMADS's own
    # "Request for Future Data" page). Conservative default -- FLAG FOR
    # HUMAN REVIEW, not independently verified as NOAA's exact SLA.
    gefs_publication_lag_hours: float = 5.0
    # How many 6-hourly cycles to step back through before giving up and
    # falling through to WeatherNext 2 Mini.
    gefs_cycle_retries: int = 4
    # Bounded concurrency for per-(member,hour) fetches -- courtesy to a
    # shared government service, not a NOAA-published hard limit. Lowered
    # from an initial 8 after observing live 302/error responses under
    # this session's own repeated high-concurrency test load.
    gefs_max_concurrent_requests: int = 5
    gefs_request_timeout_s: float = 20.0

    # ---- WeatherNext 2 Cyclones Mini (regional ensemble weather forecast) ----
    # Path to the .nc file exported by manually running wn2_demo.ipynb in
    # Colab and copying the result here (TRD §3.6 local-first: no live sync
    # dependency for demo day). Not produced by this backend.
    wn2_mini_forecast_path: Path = (
        MODULE_ROOT / "data" / "wn2_mini" / "tn_flood_forecast.nc"
    )

    # ---- CWC / India-WRIS (river & reservoir stage forecast) ----
    # Confirmed in-session (T1A.6): the National Water Data Portal is a CKAN
    # instance at this base URL, reached over its standard Action API
    # (/api/3/action/...). india_wris_base_url stays None — indiawris.gov.in
    # was unreachable from this session (connection refused); nothing about
    # it is assumed.
    cwc_data_portal_base_url: str = "https://nwdp.nwic.gov.in"
    india_wris_base_url: Optional[str] = None

    # Station-proximity threshold for T1A.7's nearest-station lookup.
    # Conservative default per the build doc's own instruction — FLAG FOR
    # HUMAN REVIEW, not a verified-correct number for this project's needs.
    cwc_station_proximity_threshold_km: float = 25.0

    # ---- Storage ----
    database_url: str = "postgresql://localhost:5432/floodsystem"
    redis_url: str = "redis://localhost:6379/0"

    # ---- Target site (for river-stage nearest-station lookup) ----
    target_site_lat: Optional[float] = None
    target_site_lon: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def _strip_inline_env_comments(cls, data: Any) -> Any:
        """Strip trailing `  # comment` text from string env values.

        BUG FOUND IN AUDIT: `.env.example` is verbatim §B.1, which uses the
        pattern `KEY=            # comment` for every field left blank for a
        later task to fill in. `python-dotenv` does not treat that as an
        empty value for an unquoted assignment — it keeps everything after
        `=` (minus leading whitespace) as the literal string, comment
        included. `env_ignore_empty` only catches a TRULY empty string, so
        every such field silently held its own comment as a "value" instead
        of falling through to this class's real default — e.g.
        `cwc_data_portal_base_url` held the literal string
        `'# confirm exact base URL in T1A.6 before hardcoding'` instead of
        this class's real default, which would have broken every request
        the CWC client made.

        Handles both shapes a blank §B.1 field produces: the whole value IS
        the comment (`dotenv` already strips the leading whitespace before
        `#`, so `KEY=            # comment` becomes the literal string
        `'# comment'` with nothing before it), and a real value followed by
        a trailing comment (`KEY=value   # comment`). A `#` NOT preceded by
        whitespace inside an otherwise-real value — e.g. a URL fragment —
        is left alone. A field that becomes empty after stripping is
        removed from the input entirely, so normal pydantic-settings
        default-filling applies to it.
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
                # else: omit the key so the field's own default applies.
            else:
                cleaned[key] = value
        return cleaned

    @field_validator("wn2_mini_forecast_path", mode="after")
    @classmethod
    def _anchor_to_module_root(cls, value: Path) -> Path:
        """Resolve a relative forecast path against the module root, not the CWD.

        `.env.example` ships `./data/wn2_mini/tn_flood_forecast.nc`, which
        would otherwise point somewhere different for every process depending on
        where it was launched from — the API server, a Celery worker, and pytest
        all have different working directories.
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
def get_settings() -> Stage1ASettings:
    """Return the process-wide settings singleton."""
    return Stage1ASettings()
