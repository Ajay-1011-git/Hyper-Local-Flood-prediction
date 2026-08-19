"""Bhuvan DEM client — T1B.2.

CONFIRMED ACCESS METHOD (sources consulted in this session):
- https://bhuvan.nrsc.gov.in/wiki/index.php/How_to_use_WMS_services —
  Bhuvan's OGC services are WMS/WMTS only (rendered map tiles); no WCS for
  raw elevation values.
- https://bhuvan-app3.nrsc.gov.in/data/download/index.php?c=s&s=C1&p=cdv2 —
  the legacy CartoDEM download page is a login-gated, browser-driven manual
  flow with no scriptable REST/API path.
- https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/ — NRSC's newer Bhoonidhi
  geoportal has a real, current, scriptable REST API (STAC-like):
    POST /auth/token                          -> bearer access_token
    GET  /data/collections                    -> list of valid collection ids
    GET|POST /data/search                     -> STAC FeatureCollection for a
                                                  collection + bbox
    GET  /download?id=&collection=             -> bearer-authed file stream
  CartoDEM is listed there under collection id "CartoSat-1_PAN_CartoDEM_30m"
  (confirmed live: GET /data/collections returned it with
  Title "CartoSat-1 PAN CartoDEM 30m").

This is the access method this client implements. It requires a real
Bhoonidhi account (BHOONIDHI_USER_ID / BHOONIDHI_PASSWORD); when unset, or
when the API rejects them, this raises a typed error rather than fabricating
a raster file — mirrors T1A's GenCastUnavailableError convention.

VERIFIED LIVE in this session (real account, real HTTP calls — not mocked):
- POST /auth/token with real credentials -> 200, real JWT access_token,
  expires_in=1200.
- POST /auth/token with wrong credentials -> real 401
  {"ErrorCode":"401","Description":"Invalid Credentials!",...}.
- GET /data/collections -> 64 collections; "CartoSat-1_PAN_CartoDEM_30m" is
  one of them.
- POST /data/search for bbox=[79.0, 12.8, 79.2, 13.0] (Vellore's region) ->
  4 STAC features, each with `properties.Online` and an `id` usable with
  /download.
- GET /download?id=P5_PAN_CD_N13_000_E079_000_30m&collection=CartoSat-1_PAN_CartoDEM_30m
  -> 200, application/octet-stream, a ~47MB ZIP
  (Content-Disposition filename="<id>.zip") containing exactly one file:
  "<id>/<id_with_DEM>.tif" — confirmed with rasterio to be a real
  EPSG:4326 GeoTIFF, shape (3600, 3600), values ranging roughly -198m to
  +1053m (physically plausible elevation, not a placeholder).

ASSUMPTION (flagged per CLAUDE.md rule 4, not independently confirmed in
docs text): the STAC `bbox` search parameter follows the standard STAC/OGC
axis order [min_lon, min_lat, max_lon, max_lat] ("west, south, east,
north"), matching every other STAC-based API and matching what worked in
the live test above. Human should sanity-check this holds for edge cases
(e.g. bboxes crossing the antimeridian — not a concern for this project's
fixed Vellore target region).

CartoDEM tiles here are 1deg x 1deg. A requested bbox may span more than one
tile, so `fetch_dem_raster` downloads every intersecting, Online tile and
mosaics them (via rasterio.merge) into a single output GeoTIFF when more
than one covers the requested area.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import requests

from backend.stage1b.config import settings
from backend.shared.contracts import BoundingBox

_TOKEN_URL_PATH = "/auth/token"
_COLLECTIONS_URL_PATH = "/data/collections"
_SEARCH_URL_PATH = "/data/search"
_DOWNLOAD_URL_PATH = "/download"

_REQUEST_TIMEOUT_S = 30
_DOWNLOAD_TIMEOUT_S = 180


class BhoonidhiCredentialsMissingError(Exception):
    """Raised when BHOONIDHI_USER_ID / BHOONIDHI_PASSWORD are not configured."""


class BhoonidhiAuthError(Exception):
    """Raised when the Bhoonidhi API rejects the configured credentials, or
    the auth call otherwise fails."""


class DemNotFoundError(Exception):
    """Raised when no CartoDEM tile covering the requested bbox is available
    (no search results, or none with `Online == "Y"`)."""


class DemDownloadError(Exception):
    """Raised when a matched tile fails to download or doesn't contain the
    expected raster file."""


def _get_access_token() -> str:
    """Authenticate against Bhoonidhi and return a bearer access token.

    Not cached across calls — Bhoonidhi tokens are short-lived (confirmed
    live: expires_in=1200s / 20 minutes) and DEM fetches are infrequent
    (once per region, not per-request), so the simplicity of re-authing each
    call outweighs the complexity of expiry tracking at this project's scale.
    """
    if not settings.bhoonidhi_user_id or not settings.bhoonidhi_password:
        raise BhoonidhiCredentialsMissingError(
            "BHOONIDHI_USER_ID / BHOONIDHI_PASSWORD are not set in .env. "
            "Register an account at https://bhoonidhi.nrsc.gov.in and set "
            "them before fetching a real DEM raster."
        )

    try:
        resp = requests.post(
            f"{settings.bhoonidhi_base_url}{_TOKEN_URL_PATH}",
            json={
                "userId": settings.bhoonidhi_user_id,
                "password": settings.bhoonidhi_password,
                "grant_type": "password",
            },
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise BhoonidhiAuthError(f"Bhoonidhi auth request failed: {exc}") from exc

    if resp.status_code != 200:
        raise BhoonidhiAuthError(
            f"Bhoonidhi auth rejected (HTTP {resp.status_code}): {resp.text}"
        )

    token = resp.json().get("access_token")
    if not token:
        raise BhoonidhiAuthError(
            f"Bhoonidhi auth response missing access_token: {resp.text}"
        )
    return token


def _search_dem_tiles(token: str, bbox: BoundingBox) -> list[dict]:
    """Search the CartoDEM collection for tiles intersecting `bbox`.

    Returns only tiles with `properties.Online == "Y"` (per the confirmed
    API docs' explicit warning that fetching Offline products causes
    fetch delays) — an Offline-only result is treated the same as "not
    found" by the caller.
    """
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, Any] = {
        "collections": [settings.bhoonidhi_dem_collection],
        "bbox": [bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat],
        "limit": 50,
    }
    try:
        resp = requests.post(
            f"{settings.bhoonidhi_base_url}{_SEARCH_URL_PATH}",
            headers=headers,
            json=body,
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise DemNotFoundError(f"Bhoonidhi search request failed: {exc}") from exc

    if resp.status_code != 200:
        raise DemNotFoundError(
            f"Bhoonidhi search failed (HTTP {resp.status_code}): {resp.text}"
        )

    features = resp.json().get("features", [])
    online = [f for f in features if f.get("properties", {}).get("Online") == "Y"]
    return online


def _download_tile(token: str, feature: dict, dest_dir: Path) -> Path:
    """Download one STAC feature's product via /download, extract its
    GeoTIFF from the delivered ZIP, and return the extracted .tif path."""
    tile_id = feature["id"]
    collection = feature["collection"]
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(
            f"{settings.bhoonidhi_base_url}{_DOWNLOAD_URL_PATH}",
            params={"id": tile_id, "collection": collection},
            headers=headers,
            timeout=_DOWNLOAD_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise DemDownloadError(f"Download request failed for {tile_id}: {exc}") from exc

    if resp.status_code != 200:
        raise DemDownloadError(
            f"Download failed for {tile_id} (HTTP {resp.status_code}): {resp.text[:500]}"
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile as exc:
        raise DemDownloadError(
            f"Downloaded content for {tile_id} is not a valid ZIP"
        ) from exc

    tif_names = [n for n in zf.namelist() if n.lower().endswith(".tif")]
    if not tif_names:
        raise DemDownloadError(
            f"No .tif file found inside downloaded archive for {tile_id} "
            f"(contents: {zf.namelist()})"
        )
    # If more than one .tif is present, prefer one with "DEM" in the name
    # (matches the confirmed real filename pattern
    # "<id>/<id-with-DEM>_30m.tif"); otherwise take the first.
    tif_name = next((n for n in tif_names if "dem" in n.lower()), tif_names[0])

    tile_dir = dest_dir / tile_id
    tile_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = tile_dir / Path(tif_name).name
    with zf.open(tif_name) as src, open(extracted_path, "wb") as dst:
        dst.write(src.read())

    return extracted_path


def _bbox_cache_key(bbox: BoundingBox) -> str:
    raw = f"{bbox.min_lat}_{bbox.max_lat}_{bbox.min_lon}_{bbox.max_lon}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fetch_dem_raster(bbox: BoundingBox) -> str:
    """Fetch the CartoDEM raster covering `bbox`, saving it under
    `DEM_RASTER_STORAGE_DIR`, and return the path to the resulting GeoTIFF.

    If `bbox` is covered by exactly one tile, that tile's extracted GeoTIFF
    is copied to the output path as-is. If covered by more than one tile
    (CartoDEM tiles are 1deg x 1deg), all intersecting tiles are mosaicked
    into a single output GeoTIFF via `rasterio.merge.merge`.

    Raises `BhoonidhiCredentialsMissingError` / `BhoonidhiAuthError` if
    credentials are missing or rejected, `DemNotFoundError` if no Online
    tile intersects `bbox`, `DemDownloadError` if a matched tile fails to
    download/extract.
    """
    token = _get_access_token()
    tiles = _search_dem_tiles(token, bbox)
    if not tiles:
        raise DemNotFoundError(
            f"No Online CartoDEM tile found intersecting bbox "
            f"(min_lat={bbox.min_lat}, max_lat={bbox.max_lat}, "
            f"min_lon={bbox.min_lon}, max_lon={bbox.max_lon})"
        )

    storage_dir = Path(settings.dem_raster_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)

    tile_paths = [_download_tile(token, feature, storage_dir) for feature in tiles]

    output_path = storage_dir / f"dem_{_bbox_cache_key(bbox)}.tif"

    if len(tile_paths) == 1:
        output_path.write_bytes(tile_paths[0].read_bytes())
        return str(output_path)

    # More than one tile: mosaic. Import rasterio lazily so a Bhoonidhi auth
    # or search failure never depends on rasterio being importable.
    import rasterio
    from rasterio.merge import merge as rasterio_merge

    srcs = [rasterio.open(p) for p in tile_paths]
    try:
        mosaic, transform = rasterio_merge(srcs)
        meta = srcs[0].meta.copy()
        meta.update(
            {
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": transform,
            }
        )
        with rasterio.open(output_path, "w", **meta) as dst:
            dst.write(mosaic)
    finally:
        for s in srcs:
            s.close()

    return str(output_path)
