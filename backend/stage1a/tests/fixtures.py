"""Synthetic, GenCast-SHAPED datasets for tests.

IMPORTANT: nothing here is a weather forecast. These builders produce arrays
with GenCast's *structure* — the `sample`/`time`/`lat`/`lon` dimensions and
the `total_precipitation_12hr` variable confirmed in T1A.2 — filled with
arbitrary deterministic numbers, purely so the parser's mapping logic can be
exercised without a TPU. Every dataset produced here is stamped
`synthetic = "yes"` in its attrs. It must never be presented as, or
substituted for, real model output.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import xarray as xr

from stage1a.gencast.client import GENCAST_MEMBER_DIM, GENCAST_PRECIP_VARIABLE

DEFAULT_START = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)


def synthetic_gencast_dataset(
    *,
    num_members: int = 2,
    lead_hours: tuple[int, ...] = (12, 24, 36, 48, 60, 72),
    lats: tuple[float, ...] = (12.75, 13.0, 13.25),
    lons: tuple[float, ...] = (79.0, 79.25, 79.5),
    units: str | None = "m",
    forecast_start: datetime = DEFAULT_START,
    use_absolute_time: bool = False,
) -> xr.Dataset:
    """Build a GenCast-shaped dataset with deterministic arbitrary values."""
    shape = (num_members, len(lead_hours), len(lats), len(lons))
    # Deterministic ramp, in metres — arbitrary, not a forecast.
    values = (
        np.arange(np.prod(shape), dtype=float).reshape(shape) / np.prod(shape) * 0.02
    )

    if use_absolute_time:
        base = np.datetime64(forecast_start.replace(tzinfo=None), "s")
        time_coord = np.array([base + np.timedelta64(h, "h") for h in lead_hours])
    else:
        time_coord = np.array(
            [np.timedelta64(h, "h") for h in lead_hours], dtype="timedelta64[ns]"
        )

    precip = xr.DataArray(
        values,
        dims=(GENCAST_MEMBER_DIM, "time", "lat", "lon"),
        coords={
            GENCAST_MEMBER_DIM: np.arange(num_members),
            "time": time_coord,
            "lat": np.array(lats),
            "lon": np.array(lons),
        },
        attrs={} if units is None else {"units": units},
    )
    return xr.Dataset(
        {GENCAST_PRECIP_VARIABLE: precip},
        attrs={
            "synthetic": "yes",
            "forecast_start": forecast_start.isoformat(),
        },
    )
