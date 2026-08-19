"""Seed the precomputed-forecast directory (development only).

READ THIS BEFORE USING IT
-------------------------
This writes a file with GenCast's *structure* and arbitrary numbers in it.
It is NOT a weather forecast and must never be presented as one. It exists
so the rest of Stage 1A — persistence, the Celery task, the API routes — can
be exercised end to end while live GenCast inference is unavailable.

Every file it writes is stamped `synthetic = "yes"`, which
`fallback.py` reads and reports as `provenance.synthetic = true`, and which
T1A.8 surfaces on the HTTP response. So anything downstream can tell that
what it received is a placeholder.

REPLACING IT WITH A REAL FORECAST
---------------------------------
On a TPU/GPU host with the GenCast stack, run inference (see
`_LIVE_INFERENCE_RECIPE` in `client.py`) and save the result directly:

    predictions.attrs["forecast_start"] = forecast_start.isoformat()
    predictions.to_netcdf(f"{forecast_id}.nc")

then copy that file into GENCAST_PRECOMPUTED_FALLBACK_DIR, deleting the
synthetic one. No code changes are needed — the loader reads GenCast's
native format, and the absence of a `synthetic` stamp is what flips
`provenance.synthetic` to false.

Usage:
    python -m stage1a.gencast.devdata --start 2026-08-19T00:00:00+00:00
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from stage1a.config import get_settings
from stage1a.gencast.client import GENCAST_MEMBER_DIM, GENCAST_PRECIP_VARIABLE
from stage1a.gencast.parser import build_forecast_id, expected_lead_hours
from stage1a.shared.contracts import BoundingBox


def build_placeholder_dataset(
    bbox: BoundingBox,
    forecast_start: datetime,
    num_members: int = 50,
    grid_step_deg: float = 0.25,
) -> xr.Dataset:
    """Build a GenCast-shaped dataset of arbitrary values, stamped synthetic."""
    lead_hours = expected_lead_hours()
    lats = np.arange(bbox.min_lat, bbox.max_lat + 1e-9, grid_step_deg)
    lons = np.arange(bbox.min_lon, bbox.max_lon + 1e-9, grid_step_deg)
    if lats.size == 0 or lons.size == 0:
        raise ValueError(f"bbox {bbox.model_dump()} is smaller than one grid cell")

    # Deterministic, seeded from the window so the same call reproduces the
    # same file. Values are in metres, matching ERA5-derived precipitation.
    seed = int(build_forecast_id(bbox, forecast_start)[-8:], 16) % (2**32)
    rng = np.random.default_rng(seed)
    values = rng.gamma(
        shape=1.5, scale=0.004, size=(num_members, len(lead_hours), lats.size, lons.size)
    )

    precip = xr.DataArray(
        values,
        dims=(GENCAST_MEMBER_DIM, "time", "lat", "lon"),
        coords={
            GENCAST_MEMBER_DIM: np.arange(num_members),
            "time": np.array(
                [np.timedelta64(h, "h") for h in lead_hours], dtype="timedelta64[ns]"
            ),
            "lat": lats,
            "lon": lons,
        },
        attrs={"units": "m", "long_name": "total precipitation over 12 hours"},
    )
    return xr.Dataset(
        {GENCAST_PRECIP_VARIABLE: precip},
        attrs={
            "synthetic": "yes",
            "synthetic_warning": (
                "PLACEHOLDER — GenCast-shaped structure with arbitrary values. "
                "Not a weather forecast. Replace with real GenCast output."
            ),
            "forecast_start": forecast_start.isoformat(),
            "source": "stage1a.gencast.devdata",
        },
    )


def write_placeholder(
    bbox: BoundingBox,
    forecast_start: datetime,
    num_members: int = 50,
    directory: Path | None = None,
) -> Path:
    """Write a placeholder forecast and return the path it was written to."""
    directory = directory or get_settings().gencast_precomputed_fallback_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{build_forecast_id(bbox, forecast_start)}.nc"
    dataset = build_placeholder_dataset(bbox, forecast_start, num_members)
    dataset.to_netcdf(path, engine="h5netcdf")
    return path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--start",
        required=True,
        help="Forecast initialisation time, ISO 8601 (e.g. 2026-08-19T00:00:00+00:00)",
    )
    parser.add_argument("--min-lat", type=float, default=12.5)
    parser.add_argument("--max-lat", type=float, default=13.3)
    parser.add_argument("--min-lon", type=float, default=78.8)
    parser.add_argument("--max-lon", type=float, default=79.5)
    parser.add_argument("--members", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    bbox = BoundingBox(
        min_lat=args.min_lat,
        max_lat=args.max_lat,
        min_lon=args.min_lon,
        max_lon=args.max_lon,
    )
    path = write_placeholder(bbox, start, args.members)
    print(f"Wrote PLACEHOLDER forecast ({args.members} members) to {path}")
    print("This is NOT a real forecast. Replace it with genuine GenCast output.")


if __name__ == "__main__":
    main()
