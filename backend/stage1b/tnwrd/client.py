"""TN WRD rainfall telemetry client — T1B.4.

CONFIRMED ACCESS METHOD (fetched and inspected for real in this session,
not assumed):
- `TNWRD_DATASET_URL` (https://nwdp.nwic.gov.in/dataset/rainfall-telemetry-
  hourly-tamil-nadu-sw-gw) is an HTML landing page, not a raw CSV — it
  lists three downloadable CSV resources (1991-2020, 2021-2025,
  2026-2030).
- The portal is CKAN (url pattern `/dataset/<id>/resource/<id>/download/
  <filename>` is CKAN's standard shape). CKAN exposes a public REST API,
  confirmed live: `GET {base}/api/3/action/package_show?id=<dataset-slug>`
  returns `result.resources`, each with a real `url`, `name`, `format`.
  This is used here to *discover* the current resource URLs rather than
  hardcoding them — CKAN resource ids/filenames are not guaranteed stable
  across dataset updates, and the confirmed API makes hardcoding
  unnecessary.
- Real column headers found in the downloaded CSVs (identical across all
  three resources, checked): `SlNo, Station, Agency, State LGD Code,
  State, District LGD Code, District, Tehsil, Block, Village, River,
  Basin, Tributary, Subtributary, SubSubtributary, Local River, Latitude,
  Longitude, Data Acquisition Time, Telemetry Hourly Rainfall (mm)`.
- `Data Acquisition Time` is `DD-MM-YYYY HH:MM` (confirmed by inspecting
  real rows, e.g. "21-02-2026 16:00") — parsed with `dayfirst=True`.
- There is no separate numeric station-id column: `Station` (a name, e.g.
  "Gollapally", "Anaikidangu") is the only per-gauge identifier present.
  ASSUMPTION (flagged per CLAUDE.md rule 4): `Station` is used as
  `station_id` in the normalized output — this is the dataset's real
  identifier, not an invented one, but note it's a name, not a stable
  numeric code, so a station rename upstream would appear as a new id.
- Confirmed: a Vellore-district station exists in the live 2026-2030 data
  ("Gollapally", District=Vellore, lat=13.03194444, lon=78.86444444) —
  per the project's instruction to check for a Vellore station before
  falling back to a nearby one. Whether it's within the nearest-station
  proximity threshold is T1B.5's job (haversine distance check), not
  this client's.

Resource sizes confirmed live (`curl -I`): 1991-2020 = 4.1KB (effectively
a near-empty placeholder), 2021-2025 = 21.9MB, 2026-2030 = 1.7MB. All
three are fetched by default — T1B.6's calibration fitting needs
historical readings, not just the current window.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import pandas as pd
import requests

from backend.stage1b.config import settings

_CKAN_PACKAGE_SHOW_PATH = "/api/3/action/package_show"
_REQUEST_TIMEOUT_S = 60

# Real, confirmed-live column names in the TN WRD CSV — not assumed.
_RAW_COLUMNS = {
    "station": "Station",
    "district": "District",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "timestamp": "Data Acquisition Time",
    "rainfall_mm": "Telemetry Hourly Rainfall (mm)",
}


class TnwrdApiError(Exception):
    """Raised when the CKAN package_show API call fails or returns an
    unexpected shape."""


class TnwrdNoResourcesFoundError(Exception):
    """Raised when the dataset's resource list has no CSV resources."""


class TnwrdDownloadError(Exception):
    """Raised when a resource CSV fails to download or parse."""


def _dataset_slug_from_url(dataset_url: str) -> str:
    """The dataset's CKAN slug is the last path segment of its landing
    page URL (e.g. ".../dataset/rainfall-telemetry-hourly-tamil-nadu-sw-gw"
    -> "rainfall-telemetry-hourly-tamil-nadu-sw-gw")."""
    return urlparse(dataset_url).path.rstrip("/").split("/")[-1]


def _base_url_from_dataset_url(dataset_url: str) -> str:
    parsed = urlparse(dataset_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_csv_resource_urls() -> list[dict]:
    """Discover this dataset's CSV resource URLs via CKAN's package_show
    API, rather than hardcoding resource ids that aren't guaranteed
    stable."""
    base_url = _base_url_from_dataset_url(settings.tnwrd_dataset_url)
    slug = _dataset_slug_from_url(settings.tnwrd_dataset_url)

    try:
        resp = requests.get(
            f"{base_url}{_CKAN_PACKAGE_SHOW_PATH}",
            params={"id": slug},
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise TnwrdApiError(f"CKAN package_show request failed: {exc}") from exc

    if resp.status_code != 200:
        raise TnwrdApiError(
            f"CKAN package_show failed (HTTP {resp.status_code}): {resp.text[:500]}"
        )

    body = resp.json()
    if not body.get("success"):
        raise TnwrdApiError(f"CKAN package_show returned success=false: {body}")

    resources = body.get("result", {}).get("resources", [])
    csv_resources = [r for r in resources if r.get("format", "").upper() == "CSV"]
    if not csv_resources:
        raise TnwrdNoResourcesFoundError(
            f"Dataset '{slug}' has no CSV-format resources (found: "
            f"{[r.get('format') for r in resources]})"
        )
    return csv_resources


def _download_and_normalize_one(resource: dict) -> pd.DataFrame:
    url = resource["url"]
    try:
        df = pd.read_csv(url, dtype=str)
    except Exception as exc:  # pandas raises various error types for bad CSVs/HTTP
        raise TnwrdDownloadError(
            f"Failed to download/parse CSV resource '{resource.get('name')}' "
            f"({url}): {exc}"
        ) from exc

    missing = [c for c in _RAW_COLUMNS.values() if c not in df.columns]
    if missing:
        raise TnwrdDownloadError(
            f"Resource '{resource.get('name')}' is missing expected columns "
            f"{missing} (found: {list(df.columns)}) — TN WRD's CSV schema may "
            f"have changed since this client was written; re-verify before "
            f"adapting the normalization."
        )

    normalized = pd.DataFrame(
        {
            "station_id": df[_RAW_COLUMNS["station"]],
            "station_name": df[_RAW_COLUMNS["station"]],
            "district": df[_RAW_COLUMNS["district"]],
            "latitude": pd.to_numeric(df[_RAW_COLUMNS["latitude"]], errors="coerce"),
            "longitude": pd.to_numeric(df[_RAW_COLUMNS["longitude"]], errors="coerce"),
            "timestamp": pd.to_datetime(
                df[_RAW_COLUMNS["timestamp"]], format="%d-%m-%Y %H:%M", errors="coerce"
            ),
            "rainfall_mm": pd.to_numeric(
                df[_RAW_COLUMNS["rainfall_mm"]], errors="coerce"
            ),
        }
    )
    return normalized


def _fetch_rainfall_telemetry_uncached() -> pd.DataFrame:
    """The real, unconditional network fetch. See `fetch_rainfall_telemetry`
    for the caching wrapper callers should normally use."""
    resources = _fetch_csv_resource_urls()
    frames = [_download_and_normalize_one(r) for r in resources]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["station_id", "timestamp"], keep="first"
    ).reset_index(drop=True)
    return combined


# In-process cache for the real telemetry download. See
# `fetch_rainfall_telemetry`'s docstring for why this exists.
_TELEMETRY_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}

#: How long a fetched telemetry snapshot stays usable before a re-fetch.
#: The upstream dataset is HOURLY telemetry, so anything under an hour
#: cannot miss a real update; 30 minutes is a deliberately conservative
#: half of that. Flagged per this project's convention for
#: unverified-optimal defaults: reasonable, not independently tuned.
TELEMETRY_CACHE_TTL_S = 1800.0


def fetch_rainfall_telemetry(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch and normalize all TN WRD hourly rainfall telemetry CSV
    resources currently listed under `TNWRD_DATASET_URL`'s CKAN dataset.

    Returns a single concatenated DataFrame with columns:
      station_id, station_name, district, latitude, longitude, timestamp,
      rainfall_mm
    (station_id/station_name are identical here — see module docstring's
    ASSUMPTION note on why: the dataset has no separate numeric station
    code).

    CACHED IN-PROCESS (2026-08-20 fix, from a real measurement not an
    assumption): this call downloads all three real CSV resources —
    ~24MB, 174,340 real rows across 145 real stations, measured at 17.2s
    wall-clock against the live portal. `routes.py` called it on EVERY
    cache-missing request, and its own comment claimed the call was
    "cheap enough ... to do per-request", which the measurement shows is
    simply false. Results are now reused for `TELEMETRY_CACHE_TTL_S`
    (well under the dataset's own hourly update cadence, so no real
    update can be missed). Pass `force_refresh=True` to bypass.

    Raises `TnwrdApiError` / `TnwrdNoResourcesFoundError` if the dataset's
    resource list can't be discovered, `TnwrdDownloadError` if a resource
    fails to download or doesn't match the expected schema.
    """
    cached = _TELEMETRY_CACHE.get("all")
    if not force_refresh and cached is not None:
        fetched_at, frame = cached
        if (time.monotonic() - fetched_at) < TELEMETRY_CACHE_TTL_S:
            return frame

    combined = _fetch_rainfall_telemetry_uncached()
    _TELEMETRY_CACHE["all"] = (time.monotonic(), combined)
    return combined
