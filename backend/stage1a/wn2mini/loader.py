"""Load a WeatherNext 2 Cyclones Mini forecast export (T1A.2, amended).

CONFIRMED BY DIRECT EXECUTION, NOT DOCUMENTATION
--------------------------------------------------
A team member ran `wn2_demo.ipynb`
(https://github.com/google-deepmind/weathernext, docs/weathernext2/) in
Colaboratory on the free TPU runtime and produced a real forecast file. This
module's structure was written by directly inspecting that file with
`xarray.open_dataset`, not by reading documentation:

    Dimensions:  (sample: 8, time: 20, batch: 1, lat: 7, lon: 7)
    Coordinates:
      * sample   int64            0 1 2 3 4 5 6 7
      * time     timedelta64[ns]  0..120h in 6h steps
      * lat      float32          8.0 .. 14.0 (1deg step)
      * lon      float32          76.0 .. 82.0 (1deg step)
    Dimensions without coordinates: batch
    Data variables:
        total_precipitation_6hr  (sample, time, batch, lat, lon) float32

Two things the confirmed file does NOT carry, which shapes this module's
design:

* **No `units` attribute** on `total_precipitation_6hr` (`attrs == {}`).
  Values range ~[-1.3e-5, 0.075] with mean ~0.0032. Interpreted as metres
  (matching the ERA5-derived convention this model family — WeatherNext 2 is
  GenCast's successor from the same repo/GCS bucket — inherits from
  GraphCast/GenCast), that is a physically plausible 0-75mm per 6h,
  consistent with a file named `tn_flood_forecast.nc`. Interpreted as
  millimetres it would cap at 0.075mm/6h — implausibly low for a flood
  forecast export. This is a **stated, documented assumption**, not a
  confirmed API fact — `WN2_PRECIP_UNITS_ASSUMED` below names it explicitly
  so it can be revisited if a differently-labelled export ever appears.
* **No `forecast_start`/global attrs at all.** Unlike the GenCast fixtures
  in `gencast/devdata.py`, nothing in the file records its own
  initialisation time. `parse_wn2_mini_output` therefore requires
  `forecast_start` as a mandatory argument — it is never inferred or
  guessed here.

The `batch` dimension (size 1, no coordinate) is an artifact of the demo
notebook's per-batch tracking loop; it is squeezed out during parsing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import xarray as xr

from stage1a.wn2mini.errors import WN2ForecastUnavailableError

WN2_MEMBER_DIM: Final[str] = "sample"
WN2_PRECIP_VARIABLE: Final[str] = "total_precipitation_6hr"
WN2_TIMESTEP_HOURS: Final[int] = 6
WN2_EXPECTED_MEMBERS: Final[int] = 8
WN2_NATIVE_RESOLUTION_KM: Final[float] = 111.0  # 1.0 deg
WN2_PRECIP_UNITS_ASSUMED: Final[str] = (
    "metres (documented assumption — the file carries no `units` attribute; "
    "see loader.py's module docstring for the physical-plausibility reasoning)"
)


def load_wn2_mini_forecast(nc_file_path: str | Path) -> xr.Dataset:
    """Load the `.nc` file at `nc_file_path`.

    Returns the dataset exactly as exported — no parsing or unit conversion
    happens here, only file access. `parser.parse_wn2_mini_output` does the
    mapping onto the §B.2 contract.

    Raises:
        WN2ForecastUnavailableError: if the file does not exist. This is the
            expected outcome before a teammate has manually copied a Colab
            export into place, and is what triggers the next fallback link.
    """
    path = Path(nc_file_path)
    if not path.is_file():
        raise WN2ForecastUnavailableError(
            f"No WeatherNext 2 Mini forecast at {path}. Run wn2_demo.ipynb in "
            "Colab and copy the exported .nc file here (manual, ahead-of-time "
            "— see WN2_MINI_FORECAST_PATH in .env.example)."
        )
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        return dataset.load()
