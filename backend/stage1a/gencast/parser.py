"""GenCast raw output -> `RegionalEnsembleForecast` (T1A.3).

The raw shape this consumes is GenCast's native `xarray.Dataset`, whose
structure was confirmed in T1A.2 (see `client.py`'s docstring for the
sources): a `sample` dimension over ensemble members, a `time` dimension at
12-hour steps, `lat`/`lon` spatial dimensions, and precipitation carried as
`total_precipitation_12hr`.

Two mapping decisions worth stating plainly, because §B.2's contract is
coarser than GenCast's output and neither gap may be papered over:

1. **Temporal.** `TimestepValue.hour` is emitted at GenCast's own 12-hour
   cadence (12, 24, ... 72), NOT interpolated to hourly. GenCast does not
   predict hourly rainfall; inventing 11 intermediate values per step would
   be fabricated data. `hour` remains an `int` in 0..72 as the contract
   requires.
2. **Spatial.** `TimestepValue.rainfall_mm` is one scalar per member per
   step, so the 2-D field inside `bbox` is reduced by an unweighted mean
   over the grid cells within the box. This is the regional-average
   rainfall, which is what §2.1 of the architecture document describes
   Stage 1 as producing before Stage 1B downscales it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Final

import numpy as np
import xarray as xr

from stage1a.gencast.client import (
    GENCAST_MEMBER_DIM,
    GENCAST_NATIVE_RESOLUTION_KM,
    GENCAST_PRECIP_VARIABLE,
    GENCAST_TIMESTEP_HOURS,
)
from stage1a.gencast.errors import GenCastParseError
from stage1a.shared.contracts import (
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    TimestepValue,
)

FORECAST_HORIZON_HOURS: Final[int] = 72

# Accepted `units` attribute values on the precipitation variable, mapped to
# the multiplier that converts them to millimetres. ERA5-derived
# precipitation is in metres, so the conversion is not optional.
_UNITS_TO_MM: Final[dict[str, float]] = {
    "m": 1000.0,
    "metre": 1000.0,
    "metres": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
    "mm": 1.0,
    "millimetre": 1.0,
    "millimetres": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "kg m-2": 1.0,  # 1 kg/m^2 of water == 1 mm depth
}

_LAT_NAMES: Final[tuple[str, ...]] = ("lat", "latitude")
_LON_NAMES: Final[tuple[str, ...]] = ("lon", "longitude")


def build_forecast_id(bbox: BoundingBox, forecast_start: datetime) -> str:
    """Return a deterministic id for `(bbox, forecast_start)`.

    Re-running for the same window must produce the same id, so persistence
    (T1A.5) can upsert rather than accumulate duplicate rows. The timestamp
    is normalised to UTC first so an equivalent instant expressed in another
    offset does not hash differently.
    """
    if forecast_start.tzinfo is None:
        normalised = forecast_start.replace(tzinfo=timezone.utc)
    else:
        normalised = forecast_start.astimezone(timezone.utc)
    payload = (
        f"{bbox.min_lat:.6f},{bbox.max_lat:.6f},"
        f"{bbox.min_lon:.6f},{bbox.max_lon:.6f}|"
        f"{normalised.isoformat()}"
    )
    return "gencast-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _spatial_dim(dataset: xr.Dataset, candidates: tuple[str, ...], axis: str) -> str:
    for name in candidates:
        if name in dataset.dims:
            return name
    raise GenCastParseError(
        f"GenCast output has no {axis} dimension; looked for {candidates!r}, "
        f"found dims {tuple(dataset.dims)!r}"
    )


def _to_mm_multiplier(variable: xr.DataArray) -> float:
    """Return the multiplier converting `variable` to millimetres.

    Raises rather than assuming a unit: silently treating metres as
    millimetres would understate rainfall by 1000x, which is exactly the
    kind of failure §A forbids defaulting through.
    """
    units = variable.attrs.get("units")
    if units is None:
        raise GenCastParseError(
            f"`{GENCAST_PRECIP_VARIABLE}` carries no `units` attribute, so its "
            "scale cannot be established. Refusing to guess — annotate the "
            f"source dataset with one of {sorted(_UNITS_TO_MM)!r}."
        )
    key = str(units).strip().lower()
    if key not in _UNITS_TO_MM:
        raise GenCastParseError(
            f"Unrecognised units {units!r} on `{GENCAST_PRECIP_VARIABLE}`; "
            f"expected one of {sorted(_UNITS_TO_MM)!r}"
        )
    return _UNITS_TO_MM[key]


def _lead_hours(dataset: xr.Dataset, forecast_start: datetime) -> list[int]:
    """Return each timestep's lead time in whole hours from `forecast_start`.

    Handles both shapes GenCast's rollout produces: a `time` coordinate of
    timedeltas relative to the initialisation, and one of absolute datetimes.
    """
    if "time" not in dataset.coords:
        raise GenCastParseError(
            f"GenCast output has no `time` coordinate; found {tuple(dataset.coords)!r}"
        )
    values = dataset["time"].values

    if np.issubdtype(values.dtype, np.timedelta64):
        deltas = values.astype("timedelta64[s]").astype(np.int64)
    elif np.issubdtype(values.dtype, np.datetime64):
        start = np.datetime64(
            forecast_start.astimezone(timezone.utc).replace(tzinfo=None), "s"
        )
        deltas = (values.astype("datetime64[s]") - start).astype(np.int64)
    else:
        raise GenCastParseError(
            f"`time` coordinate has unsupported dtype {values.dtype!r}; expected "
            "datetime64 or timedelta64"
        )

    hours: list[int] = []
    for seconds in deltas:
        if seconds % 3600 != 0:
            raise GenCastParseError(
                f"Lead time {seconds}s is not a whole number of hours; "
                "`TimestepValue.hour` is an int and must not be rounded silently"
            )
        hours.append(int(seconds // 3600))
    return hours


def parse_gencast_output(
    raw_output: xr.Dataset,
    bbox: BoundingBox,
    forecast_start: datetime | None = None,
) -> RegionalEnsembleForecast:
    """Map GenCast's native output onto the §B.2 contract.

    Args:
        raw_output: GenCast's unparsed `xarray.Dataset`, as returned by
            `run_gencast_inference` (T1A.2).
        bbox: the region the forecast was requested for; the precipitation
            field is averaged over the grid cells falling inside it.
        forecast_start: the model initialisation time, used for the
            deterministic `forecast_id`. Optional only so the signature in
            the build document still holds; when omitted it is read from the
            dataset's `forecast_start` attribute, and it is an error for
            both to be absent — guessing it would make `forecast_id`
            non-deterministic and break T1A.5's idempotency.

    Raises:
        GenCastParseError: if any contract field cannot be populated from
            the raw output. No field is ever filled with a placeholder.
    """
    if forecast_start is None:
        attr = raw_output.attrs.get("forecast_start")
        if attr is None:
            raise GenCastParseError(
                "forecast_start was not supplied and the dataset carries no "
                "`forecast_start` attribute; it is required for a deterministic "
                "forecast_id and must not be guessed."
            )
        forecast_start = (
            attr if isinstance(attr, datetime) else datetime.fromisoformat(str(attr))
        )

    if GENCAST_PRECIP_VARIABLE not in raw_output.data_vars:
        raise GenCastParseError(
            f"GenCast output has no `{GENCAST_PRECIP_VARIABLE}` variable; "
            f"found {tuple(raw_output.data_vars)!r}"
        )
    if GENCAST_MEMBER_DIM not in raw_output.dims:
        raise GenCastParseError(
            f"GenCast output has no `{GENCAST_MEMBER_DIM}` (ensemble member) "
            f"dimension; found dims {tuple(raw_output.dims)!r}"
        )

    precip = raw_output[GENCAST_PRECIP_VARIABLE]
    to_mm = _to_mm_multiplier(precip)
    lat_dim = _spatial_dim(raw_output, _LAT_NAMES, "latitude")
    lon_dim = _spatial_dim(raw_output, _LON_NAMES, "longitude")

    # Restrict to the requested box, then reduce the field to one value per
    # (member, timestep). `.sel` with a slice needs ascending coords, so
    # select by boolean mask instead — robust to either ordering.
    inside = (
        (raw_output[lat_dim] >= bbox.min_lat)
        & (raw_output[lat_dim] <= bbox.max_lat)
    )
    inside_lon = (
        (raw_output[lon_dim] >= bbox.min_lon)
        & (raw_output[lon_dim] <= bbox.max_lon)
    )
    regional = precip.where(inside & inside_lon, drop=True)
    if regional.sizes.get(lat_dim, 0) == 0 or regional.sizes.get(lon_dim, 0) == 0:
        raise GenCastParseError(
            f"No GenCast grid cells fall inside bbox {bbox.model_dump()}; "
            "cannot produce a regional average without fabricating one."
        )
    reduced = regional.mean(dim=[lat_dim, lon_dim], skipna=True)

    hours = _lead_hours(raw_output, forecast_start)
    member_ids = [int(m) for m in np.asarray(raw_output[GENCAST_MEMBER_DIM].values)]

    members: list[EnsembleMember] = []
    for index, member_id in enumerate(member_ids):
        series = np.asarray(reduced.isel({GENCAST_MEMBER_DIM: index}).values, dtype=float)
        if series.shape[0] != len(hours):
            raise GenCastParseError(
                f"Member {member_id} has {series.shape[0]} timesteps but the "
                f"`time` coordinate has {len(hours)}"
            )
        trajectory: list[TimestepValue] = []
        for hour, value in zip(hours, series):
            if hour < 0 or hour > FORECAST_HORIZON_HOURS:
                continue  # outside this system's 0-72h window (architecture §2.1)
            if not np.isfinite(value):
                raise GenCastParseError(
                    f"Member {member_id} has a non-finite rainfall value at hour "
                    f"{hour}; refusing to substitute a default."
                )
            trajectory.append(
                TimestepValue(hour=int(hour), rainfall_mm=float(value) * to_mm)
            )
        if not trajectory:
            raise GenCastParseError(
                f"Member {member_id} has no timesteps inside the 0-"
                f"{FORECAST_HORIZON_HOURS}h window"
            )
        members.append(EnsembleMember(member_id=member_id, trajectory=trajectory))

    if not members:
        raise GenCastParseError("GenCast output contains no ensemble members")

    resolution = float(
        raw_output.attrs.get("resolution_km", GENCAST_NATIVE_RESOLUTION_KM)
    )

    # `generated_at` is the model initialisation time rather than "now", so
    # re-parsing identical input yields an identical object — the same
    # determinism `forecast_id` provides.
    return RegionalEnsembleForecast(
        forecast_id=build_forecast_id(bbox, forecast_start),
        region_bbox=bbox,
        generated_at=forecast_start,
        resolution_km=resolution,
        members=members,
    )


def expected_lead_hours() -> list[int]:
    """The lead times a full 0-72h GenCast run covers, at its native cadence."""
    return list(
        range(
            GENCAST_TIMESTEP_HOURS,
            FORECAST_HORIZON_HOURS + 1,
            GENCAST_TIMESTEP_HOURS,
        )
    )
