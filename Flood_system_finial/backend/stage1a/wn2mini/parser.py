"""WeatherNext 2 Mini output -> `RegionalEnsembleForecast` (T1A.3, amended).

Mapping decisions, stated plainly (§A rule 4 — no silent assumptions):

1. **Members.** Exactly `WN2_EXPECTED_MEMBERS` (8) are required. GenCast's
   §E.1 acceptance target of 50+ members does NOT apply to this source —
   WeatherNext 2 Cyclones Mini is a smaller checkpoint. This is a real,
   confirmed behavioural difference from what the original build document
   assumed about GenCast, not something to silently absorb: any downstream
   consumer (Stage 1B's downscaling, Stage 2's simulation) that assumes 50+
   members needs to know this source provides 8.
2. **Temporal.** `TimestepValue.hour` is emitted at WN2's own 6-hour cadence
   (6, 12, ... up to whatever the file covers), never interpolated —
   inventing intermediate hourly values would be fabricated data, the same
   principle applied to any coarse-cadence forecast source. The
   confirmed file covers 0-120h, beyond this system's stated 72h horizon
   (architecture doc §1/§2.6); the extra hours are kept rather than
   discarded — persisting real data past the officially-required window
   costs nothing and may be useful later. `FORECAST_HORIZON_HOURS` here
   names the 72h requirement for reference/validation, not as a cutoff.
3. **Spatial.** Same regional-mean reduction as the GenCast parser, over the
   grid cells inside `bbox`.
4. **`forecast_start` is mandatory.** The confirmed file carries no
   attribute recording it — see `loader.py`'s docstring. Guessing it would
   make `forecast_id` non-deterministic and break T1A.5's idempotency.
5. **Units are assumed, not read.** See `WN2_PRECIP_UNITS_ASSUMED` in
   `loader.py` — the confirmed file has no `units` attribute. If a future
   export DOES carry one, it is honoured and validated against the same
   accepted-units table the GenCast parser uses; an attribute present but
   unrecognised still raises rather than guessing.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Final

import numpy as np
import xarray as xr

from stage1a.shared.contracts import (
    BoundingBox,
    EnsembleMember,
    RegionalEnsembleForecast,
    TimestepValue,
)
from stage1a.wn2mini.errors import WN2ParseError
from stage1a.wn2mini.loader import (
    WN2_EXPECTED_MEMBERS,
    WN2_MEMBER_DIM,
    WN2_NATIVE_RESOLUTION_KM,
    WN2_PRECIP_VARIABLE,
    WN2_TIMESTEP_HOURS,
)

#: This system's officially-required forecast horizon (architecture §1,
#: §2.6). Named here for validation/reference; WN2 Mini's confirmed 120h
#: coverage exceeds it and is kept rather than truncated — see module
#: docstring point 2.
FORECAST_HORIZON_HOURS: Final[int] = 72

_LAT_NAMES: Final[tuple[str, ...]] = ("lat", "latitude")
_LON_NAMES: Final[tuple[str, ...]] = ("lon", "longitude")
_BATCH_DIM: Final[str] = "batch"

# Accepted `units` attribute values on the precipitation variable, mapped to
# the multiplier that converts them to millimetres.
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


def build_forecast_id(bbox: BoundingBox, forecast_start: datetime) -> str:
    """Deterministic id for `(bbox, forecast_start)`, WN2-namespaced.

    Namespaced with a `wn2mini-` prefix so this source's forecasts are
    unambiguously distinguishable from any future source's in the shared
    `forecast_id`-keyed table.
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
    return "wn2mini-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _spatial_dim(dataset: xr.Dataset, candidates: tuple[str, ...], axis: str) -> str:
    for name in candidates:
        if name in dataset.dims:
            return name
    raise WN2ParseError(
        f"WN2 Mini output has no {axis} dimension; looked for {candidates!r}, "
        f"found dims {tuple(dataset.dims)!r}"
    )


def _to_mm_multiplier(variable: xr.DataArray) -> float:
    """Return the mm multiplier, honouring a `units` attr if present.

    Falls back to the documented metres assumption (see loader.py) only
    when no `units` attribute exists at all — an attribute that IS present
    but unrecognised still raises, exactly like the GenCast parser.
    """
    units = variable.attrs.get("units")
    if units is None:
        return _UNITS_TO_MM["m"]
    key = str(units).strip().lower()
    if key not in _UNITS_TO_MM:
        raise WN2ParseError(
            f"Unrecognised units {units!r} on `{WN2_PRECIP_VARIABLE}`; "
            f"expected one of {sorted(_UNITS_TO_MM)!r}"
        )
    return _UNITS_TO_MM[key]


def _lead_hours(dataset: xr.Dataset) -> list[int]:
    """Return each timestep's lead time in whole hours.

    The confirmed file's `time` coordinate is always a timedelta64 offset
    from initialisation (never absolute datetimes, unlike GenCast's rollout
    output) — see loader.py's module docstring.
    """
    if "time" not in dataset.coords:
        raise WN2ParseError(
            f"WN2 Mini output has no `time` coordinate; found {tuple(dataset.coords)!r}"
        )
    values = dataset["time"].values
    if not np.issubdtype(values.dtype, np.timedelta64):
        raise WN2ParseError(
            f"`time` coordinate has unsupported dtype {values.dtype!r}; expected "
            "timedelta64, per the confirmed file structure"
        )
    deltas = values.astype("timedelta64[s]").astype(np.int64)
    hours: list[int] = []
    for seconds in deltas:
        if seconds % 3600 != 0:
            raise WN2ParseError(
                f"Lead time {seconds}s is not a whole number of hours; "
                "`TimestepValue.hour` is an int and must not be rounded silently"
            )
        hours.append(int(seconds // 3600))
    return hours


def parse_wn2_mini_output(
    raw_output: xr.Dataset,
    bbox: BoundingBox,
    forecast_start: datetime,
) -> RegionalEnsembleForecast:
    """Map a WeatherNext 2 Mini export onto the §B.2 contract.

    Args:
        raw_output: as returned by `wn2mini.loader.load_wn2_mini_forecast`.
        bbox: the region to average precipitation over.
        forecast_start: the model initialisation time. MANDATORY — the
            confirmed file records no such attribute, so it cannot be read
            back; see the module docstring.

    Raises:
        WN2ParseError: if any contract field cannot be populated from the
            raw output, or the member count does not match
            `WN2_EXPECTED_MEMBERS`. No field is ever filled with a
            placeholder.
    """
    if WN2_PRECIP_VARIABLE not in raw_output.data_vars:
        raise WN2ParseError(
            f"WN2 Mini output has no `{WN2_PRECIP_VARIABLE}` variable; "
            f"found {tuple(raw_output.data_vars)!r}"
        )
    if WN2_MEMBER_DIM not in raw_output.dims:
        raise WN2ParseError(
            f"WN2 Mini output has no `{WN2_MEMBER_DIM}` (ensemble member) "
            f"dimension; found dims {tuple(raw_output.dims)!r}"
        )

    member_count = raw_output.sizes[WN2_MEMBER_DIM]
    if member_count != WN2_EXPECTED_MEMBERS:
        raise WN2ParseError(
            f"WN2 Mini output has {member_count} members; expected exactly "
            f"{WN2_EXPECTED_MEMBERS}. Proceeding with a different count would "
            "silently change what downstream consumers think this source "
            "provides."
        )

    precip = raw_output[WN2_PRECIP_VARIABLE]
    if _BATCH_DIM in precip.dims:
        if precip.sizes[_BATCH_DIM] != 1:
            raise WN2ParseError(
                f"WN2 Mini output has {precip.sizes[_BATCH_DIM]} batch entries; "
                "expected exactly 1, per the confirmed file structure"
            )
        precip = precip.isel({_BATCH_DIM: 0}, drop=True)

    to_mm = _to_mm_multiplier(precip)
    lat_dim = _spatial_dim(raw_output, _LAT_NAMES, "latitude")
    lon_dim = _spatial_dim(raw_output, _LON_NAMES, "longitude")

    inside_lat = (raw_output[lat_dim] >= bbox.min_lat) & (
        raw_output[lat_dim] <= bbox.max_lat
    )
    inside_lon = (raw_output[lon_dim] >= bbox.min_lon) & (
        raw_output[lon_dim] <= bbox.max_lon
    )
    regional = precip.where(inside_lat & inside_lon, drop=True)
    if regional.sizes.get(lat_dim, 0) == 0 or regional.sizes.get(lon_dim, 0) == 0:
        raise WN2ParseError(
            f"No WN2 Mini grid cells fall inside bbox {bbox.model_dump()}; "
            "cannot produce a regional average without fabricating one. The "
            "confirmed export covers lat 8-14 deg, lon 76-82 deg (Tamil Nadu)."
        )
    reduced = regional.mean(dim=[lat_dim, lon_dim], skipna=True)

    hours = _lead_hours(raw_output)
    member_ids = [int(m) for m in np.asarray(raw_output[WN2_MEMBER_DIM].values)]

    members: list[EnsembleMember] = []
    for index, member_id in enumerate(member_ids):
        series = np.asarray(
            reduced.isel({WN2_MEMBER_DIM: index}).values, dtype=float
        )
        if series.shape[0] != len(hours):
            raise WN2ParseError(
                f"Member {member_id} has {series.shape[0]} timesteps but the "
                f"`time` coordinate has {len(hours)}"
            )
        trajectory: list[TimestepValue] = []
        for hour, value in zip(hours, series):
            if not np.isfinite(value):
                raise WN2ParseError(
                    f"Member {member_id} has a non-finite rainfall value at "
                    f"hour {hour}; refusing to substitute a default."
                )
            # Negative accumulated precipitation is a known small numerical
            # artifact in diffusion-model output near-zero rainfall (the
            # confirmed file's min is -1.3e-5 m); clamp to zero rather than
            # reporting physically impossible negative rainfall.
            trajectory.append(
                TimestepValue(hour=int(hour), rainfall_mm=max(0.0, float(value) * to_mm))
            )
        members.append(EnsembleMember(member_id=member_id, trajectory=trajectory))

    return RegionalEnsembleForecast(
        forecast_id=build_forecast_id(bbox, forecast_start),
        source="WeatherNext2_Cyclones_Mini",
        region_bbox=bbox,
        generated_at=forecast_start,
        resolution_km=WN2_NATIVE_RESOLUTION_KM,
        members=members,
    )


def expected_lead_hours(max_hour: int = 120) -> list[int]:
    """Lead times WN2 Mini's confirmed 6-hourly cadence covers, up to `max_hour`."""
    return list(range(WN2_TIMESTEP_HOURS, max_hour + 1, WN2_TIMESTEP_HOURS))
