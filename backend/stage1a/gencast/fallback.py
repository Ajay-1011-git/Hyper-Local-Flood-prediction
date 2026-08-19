"""Precomputed GenCast forecast loader, and Stage 1A's overall source chain (T1A.4).

CHAIN UPDATED by the 2026-08-19 amendment. `get_regional_forecast` is now
the entry point for the FULL acquisition chain, not just the GenCast
live/fallback pair:

    1. GEFS               (gefs.client — NOT implemented, always unavailable)
    2. WeatherNext 2 Mini  (wn2mini — real, confirmed-working, manual export)
    3. legacy GenCast path (this module's original live-inference-then-
                             precomputed-fallback pair, kept as the final
                             resort exactly as T1A.2-T1A.4 originally built it)

Order was an explicit human decision, not a default: GEFS is fully
automated with no manual step, so it should be tried first once it exists;
WeatherNext 2 Mini requires a human to run a Colab notebook ahead of time,
so it is asked for only once GEFS has nothing.

Why the GenCast pair still exists
----------------------------------
T1A.2 established that live GenCast inference needs the `weathernext`
package and JAX on a TPU/GPU, which most hosts do not have. Rather than
failing the whole pipeline there, this module loads a forecast that was
computed elsewhere (a Colab/Cloud TPU session) and carried over as a file.
This is now the LAST link in the chain rather than the primary path — see
above — but nothing about it was wrong, so the audit before this amendment
kept it rather than deleting working, tested code.

File format
-----------
NetCDF holding GenCast's own `xarray.Dataset` — the same object
`run_gencast_inference` returns — so a forecast produced on a TPU can be
written with `predictions.to_netcdf(...)` and dropped straight into
`GENCAST_PRECOMPUTED_FALLBACK_DIR` with no re-encoding step.

Lookup is by the deterministic `forecast_id` from T1A.3
(`<forecast_id>.nc`); failing that, every `*.nc` in the directory is
inspected and matched on its `forecast_start` attribute and grid coverage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import xarray as xr

from stage1a.config import Stage1ASettings, get_settings
from stage1a.gencast.client import run_gencast_inference
from stage1a.gencast.errors import (
    GenCastUnavailableError,
    NoFallbackAvailableError,
)
from stage1a.gencast.parser import build_forecast_id, parse_gencast_output
from stage1a.gencast.provenance import (
    ForecastPath,
    ForecastProvenance,
    RegionalForecastResult,
)
from stage1a.gefs.client import fetch_gefs_forecast
from stage1a.gefs.errors import GEFSUnavailableError
from stage1a.shared.contracts import BoundingBox, RegionalEnsembleForecast
from stage1a.wn2mini.errors import WN2ForecastUnavailableError
from stage1a.wn2mini.loader import load_wn2_mini_forecast
from stage1a.wn2mini.parser import parse_wn2_mini_output

logger = logging.getLogger(__name__)

_LAT_NAMES = ("lat", "latitude")
_LON_NAMES = ("lon", "longitude")


def _is_synthetic(dataset: xr.Dataset) -> bool:
    """True if the dataset is stamped as a development fixture."""
    return str(dataset.attrs.get("synthetic", "")).strip().lower() in {
        "yes",
        "true",
        "1",
    }


def _covers_bbox(dataset: xr.Dataset, bbox: BoundingBox) -> bool:
    """True if the dataset's grid has at least one cell inside `bbox`."""
    lat_name = next((n for n in _LAT_NAMES if n in dataset.coords), None)
    lon_name = next((n for n in _LON_NAMES if n in dataset.coords), None)
    if lat_name is None or lon_name is None:
        return False
    lats = dataset[lat_name].values
    lons = dataset[lon_name].values
    has_lat = bool(((lats >= bbox.min_lat) & (lats <= bbox.max_lat)).any())
    has_lon = bool(((lons >= bbox.min_lon) & (lons <= bbox.max_lon)).any())
    return has_lat and has_lon


def _matches_start(dataset: xr.Dataset, forecast_start: datetime) -> bool:
    """True if the dataset's `forecast_start` attribute equals `forecast_start`."""
    attr = dataset.attrs.get("forecast_start")
    if attr is None:
        return False
    try:
        parsed = (
            attr if isinstance(attr, datetime) else datetime.fromisoformat(str(attr))
        )
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    target = (
        forecast_start
        if forecast_start.tzinfo
        else forecast_start.replace(tzinfo=timezone.utc)
    )
    return parsed.astimezone(timezone.utc) == target.astimezone(timezone.utc)


def _open(path: Path) -> xr.Dataset:
    """Open a NetCDF forecast, loading it eagerly so the file handle can close."""
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        return dataset.load()


def find_precomputed_file(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> Optional[Path]:
    """Return the precomputed file for this window, or None if there isn't one."""
    settings = settings or get_settings()
    directory = settings.gencast_precomputed_fallback_dir
    if not directory.is_dir():
        return None

    exact = directory / f"{build_forecast_id(bbox, forecast_start)}.nc"
    if exact.is_file():
        return exact

    for candidate in sorted(directory.glob("*.nc")):
        try:
            dataset = _open(candidate)
        except (OSError, ValueError) as exc:
            logger.warning("Skipping unreadable precomputed file %s: %s", candidate, exc)
            continue
        if _matches_start(dataset, forecast_start) and _covers_bbox(dataset, bbox):
            return candidate
    return None


def load_precomputed_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalEnsembleForecast:
    """Load the precomputed forecast for `(bbox, forecast_start)`.

    Raises:
        NoFallbackAvailableError: if no matching file exists. An empty or
            invented forecast is never returned in its place.
    """
    settings = settings or get_settings()
    path = find_precomputed_file(bbox, forecast_start, settings)
    if path is None:
        raise NoFallbackAvailableError(
            "No precomputed GenCast forecast for "
            f"start={forecast_start.isoformat()} bbox={bbox.model_dump()} in "
            f"{settings.gencast_precomputed_fallback_dir}. Produce one on a "
            "TPU/GPU host and save it with `predictions.to_netcdf(...)` as "
            f"'{build_forecast_id(bbox, forecast_start)}.nc'."
        )
    return parse_gencast_output(_open(path), bbox, forecast_start)


def load_precomputed_result(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
    fallback_reason: Optional[str] = None,
) -> RegionalForecastResult:
    """`load_precomputed_forecast`, plus the provenance of what was loaded."""
    settings = settings or get_settings()
    path = find_precomputed_file(bbox, forecast_start, settings)
    if path is None:
        raise NoFallbackAvailableError(
            "No precomputed GenCast forecast for "
            f"start={forecast_start.isoformat()} bbox={bbox.model_dump()} in "
            f"{settings.gencast_precomputed_fallback_dir}"
        )
    dataset = _open(path)
    forecast = parse_gencast_output(dataset, bbox, forecast_start)
    return RegionalForecastResult(
        forecast=forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.FALLBACK,
            retrieved_at=datetime.now(timezone.utc),
            source_file=str(path),
            synthetic=_is_synthetic(dataset),
            fallback_reason=fallback_reason,
        ),
    )


def _try_wn2_mini(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Stage1ASettings,
) -> RegionalForecastResult:
    """Load and parse the manually-exported WeatherNext 2 Mini file.

    Raises:
        WN2ForecastUnavailableError: if no file exists at the configured
            path — propagated to the caller so it can try the next link.
        wn2mini.errors.WN2ParseError: if the file exists but is malformed.
            NOT caught here — a broken export is a real bug, not something
            to silently fall through on.
    """
    dataset = load_wn2_mini_forecast(settings.wn2_mini_forecast_path)
    forecast = parse_wn2_mini_output(dataset, bbox, forecast_start)
    return RegionalForecastResult(
        forecast=forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.WN2_MINI,
            retrieved_at=datetime.now(timezone.utc),
            source_file=str(settings.wn2_mini_forecast_path),
            synthetic=False,
        ),
    )


def _try_legacy_gencast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Stage1ASettings,
) -> RegionalForecastResult:
    """The original T1A.2-T1A.4 live-inference/synthetic-fallback pair.

    Only `GenCastUnavailableError` triggers the synthetic fallback within
    this pair. A parse failure or any other error propagates.
    """
    try:
        raw = run_gencast_inference(bbox, forecast_start, settings=settings)
    except GenCastUnavailableError as exc:
        logger.warning(
            "GenCast live inference unavailable (%s); falling back to a "
            "precomputed forecast",
            exc,
        )
        return load_precomputed_result(
            bbox, forecast_start, settings, fallback_reason=str(exc)
        )

    logger.info("GenCast live inference succeeded for %s", forecast_start.isoformat())
    return RegionalForecastResult(
        forecast=parse_gencast_output(raw, bbox, forecast_start),
        provenance=ForecastProvenance(
            path=ForecastPath.LIVE,
            retrieved_at=datetime.now(timezone.utc),
            synthetic=_is_synthetic(raw),
        ),
    )


def get_regional_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Return the regional forecast, trying each source in the chain in order.

    Chain (amendment, 2026-08-19): GEFS -> WeatherNext 2 Mini -> legacy
    GenCast (live inference, then its own synthetic fallback). See the
    module docstring for why this order.

    Only each link's own "unavailable" error advances to the next link. A
    parse failure or any other error propagates immediately — a source that
    exists but is malformed is a real bug, not a reason to quietly serve a
    different one.

    Raises:
        NoFallbackAvailableError: if every link in the chain is exhausted.
    """
    settings = settings or get_settings()

    try:
        return fetch_gefs_forecast(bbox, forecast_start, settings)
    except GEFSUnavailableError as exc:
        logger.info("%s Trying WeatherNext 2 Mini next.", exc)

    try:
        return _try_wn2_mini(bbox, forecast_start, settings)
    except WN2ForecastUnavailableError as exc:
        logger.warning("%s Falling back to the legacy GenCast path.", exc)

    return _try_legacy_gencast(bbox, forecast_start, settings)
