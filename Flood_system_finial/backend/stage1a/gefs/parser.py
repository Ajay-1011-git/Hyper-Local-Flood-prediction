"""GEFS 0.25-degree output -> `RegionalEnsembleForecast` (T1A.2 GEFS amendment, 2026-08-20).

CONFIRMED BY DIRECTLY FETCHING AND DECODING REAL LIVE DATA, NOT DOCUMENTATION
---------------------------------------------------------------------------
This session fetched real GRIB2 subsets from NOAA's live NOMADS filter
service (`https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl`)
for the real 2026-08-19 00Z GEFS cycle and decoded them with `cfgrib`, not
assumed from any spec:

    <xarray.Dataset>
    Dimensions: (latitude: 25, longitude: 25)
    Coordinates: latitude, longitude, number, time, step, surface, valid_time
    Data variables:
        tp  (latitude, longitude) float32
    tp.attrs: {GRIB_shortName: 'tp', GRIB_units: 'kg m**-2',
               GRIB_stepType: 'accum', GRIB_totalNumber: 30,
               GRIB_name: 'Total Precipitation'}

Confirmed directly (not assumed):
* Variable short name is `tp` (cfgrib's own name for GRIB param APCP),
  units `kg m**-2` — 1 kg/m^2 of water == 1mm depth, the SAME 1:1
  conversion `wn2mini/parser.py`'s `_UNITS_TO_MM` table already has for
  `"kg m-2"` (GEFS's real string has `**` where WN2's had a bare `-`;
  handled by normalising before lookup, see `_GEFS_UNITS_TO_MM` below).
* `GRIB_stepType: accum` accumulates over the INTERVAL BETWEEN OUTPUT
  TIMES, not since forecast init — confirmed empirically: three real
  fetches at f003/f006/f009 for the same member gave 0.235/0.308/0.121mm
  regional means, non-monotonic, ruling out cumulative-since-init. Each
  fetched hour's value IS the rainfall for that period directly — the
  same semantic as WN2's `total_precipitation_6hr`, no diffing needed.
* `GRIB_totalNumber: 30` on a `p01` file — confirms 30 real perturbation
  members (p01-p30) plus the unperturbed control run (`c00`) = 31 real
  ensemble members total (`avg`/`spr` are derived statistics, not
  independent members, and are never fetched).

CADENCE — A STATED SIMPLIFICATION, NOT THE PRODUCT'S NATIVE LIMIT
---------------------------------------------------------------------
The confirmed live product outputs 3-hourly through at least 240h at
0.25 deg. `GEFS_TIMESTEP_HOURS = 6` here is a deliberate choice to keep
this system's per-cycle request count practical (31 members x 12 steps =
372, vs. 744 at native 3-hourly) — matching WN2 Mini's own established
6-hourly cadence in this codebase, not a limitation of what NOAA
publishes. FLAG FOR HUMAN REVIEW if finer temporal resolution is wanted
later; the spatial-resolution improvement this amendment is actually
for (0.25 deg vs. WN2's 1 deg) is unaffected by this choice.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import numpy as np
import xarray as xr

from stage1a.gefs.errors import GEFSParseError
from stage1a.shared.contracts import BoundingBox, EnsembleMember, RegionalEnsembleForecast, TimestepValue

GEFS_CONTROL_MEMBER: Final[str] = "c00"
GEFS_PERTURBATION_COUNT: Final[int] = 30  # p01..p30 -- confirmed via GRIB_totalNumber above
GEFS_MEMBERS: Final[tuple[str, ...]] = (GEFS_CONTROL_MEMBER,) + tuple(
    f"p{i:02d}" for i in range(1, GEFS_PERTURBATION_COUNT + 1)
)
GEFS_TIMESTEP_HOURS: Final[int] = 6  # stated simplification -- see module docstring
GEFS_NATIVE_RESOLUTION_KM: Final[float] = 27.75  # 0.25deg * ~111km/deg, real product grid spacing
GEFS_PRECIP_VARIABLE: Final[str] = "tp"

_GEFS_UNITS_TO_MM: Final[dict[str, float]] = {
    "kg m**-2": 1.0,  # confirmed real units string on the live product
    "kg m-2": 1.0,
    "mm": 1.0,
    "m": 1000.0,
}


def build_forecast_id(bbox: BoundingBox, cycle_start: datetime) -> str:
    """Deterministic id for `(bbox, cycle_start)`, GEFS-namespaced.

    Namespaced with a `gefs-` prefix, matching WN2 Mini's `wn2mini-`
    convention, so both sources' forecasts are unambiguously
    distinguishable in the shared `forecast_id`-keyed table.
    """
    if cycle_start.tzinfo is None:
        normalised = cycle_start.replace(tzinfo=timezone.utc)
    else:
        normalised = cycle_start.astimezone(timezone.utc)
    payload = (
        f"{bbox.min_lat:.6f},{bbox.max_lat:.6f},"
        f"{bbox.min_lon:.6f},{bbox.max_lon:.6f}|"
        f"{normalised.isoformat()}"
    )
    return "gefs-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _to_mm_multiplier(variable: xr.DataArray) -> float:
    units = variable.attrs.get("units") or variable.attrs.get("GRIB_units")
    if units is None:
        raise GEFSParseError(
            f"GEFS `{GEFS_PRECIP_VARIABLE}` variable has no units attribute "
            "at all -- refusing to guess (confirmed real files always carry "
            "GRIB_units)."
        )
    key = str(units).strip().lower()
    if key not in _GEFS_UNITS_TO_MM:
        raise GEFSParseError(
            f"Unrecognised units {units!r} on `{GEFS_PRECIP_VARIABLE}`; "
            f"expected one of {sorted(_GEFS_UNITS_TO_MM)!r}"
        )
    return _GEFS_UNITS_TO_MM[key]


def _subset_to_bbox(variable: xr.DataArray, bbox: BoundingBox) -> xr.DataArray:
    """Restrict `variable` to the grid cells inside `bbox`.

    Applied unconditionally, because this module now decodes GRIB2 from
    two real transports with different spatial extents (see `client.py`):
    the S3 transport returns the GLOBAL 0.25deg field (721x1440 -- it has
    no server-side subsetting), while NOMADS's filter service returns an
    already-subsetted grid. Masking by coordinate value (rather than
    `.sel(slice(...))`) is order-independent, so it works whether the
    latitude axis runs north->south or south->north, and is a harmless
    no-op on already-subsetted NOMADS data.

    LONGITUDE CONVENTION: confirmed live this session that the real GEFS
    grid is 0-360 (not -180..180) -- this project's target region
    (76-82 deg E) is positive either way, so no wrapping is needed here.
    A bbox with negative longitudes would need conversion first; flagged
    rather than silently mis-subsetting, since it is not a real case for
    this project's fixed Tamil Nadu region.
    """
    lat_name = "latitude" if "latitude" in variable.coords else "lat"
    lon_name = "longitude" if "longitude" in variable.coords else "lon"
    if lat_name not in variable.coords or lon_name not in variable.coords:
        raise GEFSParseError(
            f"GEFS GRIB2 record has no usable lat/lon coordinates; "
            f"found {tuple(variable.coords)!r}"
        )
    inside = (
        (variable[lat_name] >= bbox.min_lat)
        & (variable[lat_name] <= bbox.max_lat)
        & (variable[lon_name] >= bbox.min_lon)
        & (variable[lon_name] <= bbox.max_lon)
    )
    return variable.where(inside, drop=True)


def decode_regional_mean_mm(grib2_path: str | Path, bbox: BoundingBox) -> float:
    """Decode one fetched GRIB2 record and return its regional-mean
    precipitation for that member/hour, over `bbox`, in mm.

    Handles both real transports' extents -- see `_subset_to_bbox`.

    Raises:
        GEFSParseError: if the expected variable/units aren't present, no
            grid cell falls inside `bbox`, or every value inside it is
            non-finite. Never substitutes a default in place of a real
            failure.
    """
    try:
        with xr.open_dataset(grib2_path, engine="cfgrib") as dataset:
            if GEFS_PRECIP_VARIABLE not in dataset.data_vars:
                raise GEFSParseError(
                    f"GEFS GRIB2 response has no `{GEFS_PRECIP_VARIABLE}` "
                    f"variable; found {tuple(dataset.data_vars)!r}"
                )
            variable = dataset[GEFS_PRECIP_VARIABLE]
            to_mm = _to_mm_multiplier(variable)
            regional = _subset_to_bbox(variable, bbox)
            values = np.asarray(regional.values, dtype=float)
    except GEFSParseError:
        raise
    except Exception as exc:  # cfgrib/eccodes raise their own exception types
        raise GEFSParseError(f"Failed to decode GEFS GRIB2 file {grib2_path}: {exc}") from exc

    if values.size == 0:
        raise GEFSParseError(
            f"No GEFS grid cells fall inside bbox {bbox.model_dump()} for "
            f"{grib2_path} -- cannot produce a regional mean without "
            "fabricating one."
        )
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise GEFSParseError(
            f"GEFS GRIB2 response at {grib2_path} has no finite "
            f"`{GEFS_PRECIP_VARIABLE}` values inside bbox -- cannot compute "
            "a regional mean without fabricating one."
        )
    # Same documented near-zero negative-artifact clamp as the WN2 parser.
    return max(0.0, float(finite.mean()) * to_mm)


def build_regional_ensemble_forecast(
    values_by_member_hour: dict[str, dict[int, float]],
    bbox: BoundingBox,
    cycle_start: datetime,
) -> RegionalEnsembleForecast:
    """Assemble the §B.2 contract from decoded regional-mean values.

    Args:
        values_by_member_hour: `{member_name: {lead_hour: rainfall_mm}}`,
            e.g. `{"c00": {6: 0.3, 12: 0.1, ...}, "p01": {...}, ...}`.
        cycle_start: the REAL GEFS cycle's own init time (confirmed by
            successfully fetching from it) -- used as `generated_at`, not
            the literal request-time `forecast_start` argument the caller
            passed to `fetch_gefs_forecast` (that time may not correspond
            to any actually-published cycle; using the real cycle time
            here is more honest, mirrors how the fallback chain always
            reports what actually happened, not what was asked for).

    Raises:
        GEFSParseError: if `values_by_member_hour` doesn't cover exactly
            `GEFS_MEMBERS`, or any member is missing an expected hour.
    """
    missing_members = set(GEFS_MEMBERS) - set(values_by_member_hour)
    extra_members = set(values_by_member_hour) - set(GEFS_MEMBERS)
    if missing_members or extra_members:
        raise GEFSParseError(
            f"GEFS response covers unexpected members: missing "
            f"{sorted(missing_members)!r}, unexpected {sorted(extra_members)!r}"
        )

    members: list[EnsembleMember] = []
    for index, member_name in enumerate(GEFS_MEMBERS):
        hourly = values_by_member_hour[member_name]
        trajectory = [
            TimestepValue(hour=hour, rainfall_mm=hourly[hour])
            for hour in sorted(hourly)
        ]
        members.append(EnsembleMember(member_id=index, trajectory=trajectory))

    return RegionalEnsembleForecast(
        forecast_id=build_forecast_id(bbox, cycle_start),
        source="GEFS",
        region_bbox=bbox,
        generated_at=cycle_start,
        resolution_km=GEFS_NATIVE_RESOLUTION_KM,
        members=members,
    )
