"""Precomputed GenCast forecast loader and the live/fallback orchestrator (T1A.4).

Why this exists
---------------
T1A.2 established that live GenCast inference needs the `weathernext`
package and JAX on a TPU/GPU, which most hosts do not have. Rather than
failing the whole pipeline there, this module loads a forecast that was
computed elsewhere (a Colab/Cloud TPU session) and carried over as a file.

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
from stage1a.shared.contracts import BoundingBox, RegionalEnsembleForecast

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


def get_regional_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Return the regional forecast, trying live inference before the fallback.

    Only `GenCastUnavailableError` triggers the fallback. A parse failure or
    any other error propagates — a forecast that exists but is malformed is a
    real bug, not a reason to quietly serve a different one.

    Raises:
        NoFallbackAvailableError: if live inference is unavailable AND no
            precomputed forecast exists for the window.
    """
    settings = settings or get_settings()
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
