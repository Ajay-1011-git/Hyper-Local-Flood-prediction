"""Downscaling orchestration: RegionalEnsembleForecast -> DownscaledForecastField — T1B.8.

`generate_downscaled_field` ties T1B.2–T1B.7 together: for every ensemble
member and every timestep in a `RegionalEnsembleForecast` (Stage 1A's
output contract), samples T1B.3's terrain grid at the target site's exact
coordinates and applies T1B.7's `downscale_rainfall` with T1B.6's fitted
coefficients, producing a `DownscaledForecastField`.

STAGE 1A STATUS AT TIME OF WRITING: Stage 1A (which produces
`RegionalEnsembleForecast`) is being built independently by a different
team member and has no live endpoint in this repo yet. Per this project's
own explicit instruction for exactly this situation — "for development
before Stage 1A's endpoint exists, use a mock fixture, clearly labeled as
such, not a fabricated 'real' call" — this module's function accepts any
`RegionalEnsembleForecast`-shaped object (real or mock) and does not care
which; the VERIFY run in this task's commit message uses a mock fixture
built directly from `backend.shared.contracts.RegionalEnsembleForecast`,
explicitly named and commented as a mock in the verification script, not
presented as a real Stage 1A call.
"""

from __future__ import annotations

from datetime import datetime, timezone

import rasterio
from rasterio.warp import transform as warp_transform

from backend.shared.contracts import (
    DownscaledEnsembleMember,
    DownscaledForecastField,
    DownscaledTimestepValue,
    RegionalEnsembleForecast,
)
from backend.stage1b.downscaling.model import downscale_rainfall


class SiteOutsideTerrainGridError(Exception):
    """Raised when `(site_lat, site_lon)` falls outside the terrain grid
    referenced by `terrain_grid_path` — never silently clamps to the
    nearest edge cell and pretends that's the real value at the site."""


def _sample_terrain_at_site(
    terrain_grid_path: str, site_lat: float, site_lon: float
) -> tuple[float, float, float]:
    """Return (elevation_m, slope_deg, aspect_deg) sampled from T1B.3's
    3-band GeoTIFF (band order: 1=elevation, 2=slope_deg, 3=aspect_deg) at
    the grid cell nearest `(site_lat, site_lon)`."""
    with rasterio.open(terrain_grid_path) as src:
        try:
            xs, ys = warp_transform("EPSG:4326", src.crs, [site_lon], [site_lat])
        except Exception as exc:
            # PROJ raises here for coordinates entirely outside the target
            # CRS's valid domain (e.g. (0, 0) reprojected into a Vellore-
            # area UTM zone) — a real failure mode, not a theoretical one
            # (caught by actually trying it during development). It surfaces
            # as rasterio._err.CPLE_AppDefinedError, a GDAL/CPL error wrapper
            # that inherits only from bare Exception (not
            # rasterio.errors.RasterioError or anything else catchable more
            # narrowly) — confirmed by inspecting its actual __mro__, not
            # assumed. Same underlying situation as the explicit bounds
            # check below (site nowhere near this terrain grid), so it gets
            # the same typed error rather than leaking a raw PROJ exception.
            raise SiteOutsideTerrainGridError(
                f"Site ({site_lat}, {site_lon}) could not be reprojected "
                f"into the terrain grid's CRS ({src.crs}) at "
                f"{terrain_grid_path}: {exc}"
            ) from exc

        col, row = ~src.transform * (xs[0], ys[0])
        row, col = int(row), int(col)

        if not (0 <= row < src.height and 0 <= col < src.width):
            raise SiteOutsideTerrainGridError(
                f"Site ({site_lat}, {site_lon}) maps to grid cell (row={row}, "
                f"col={col}), outside the terrain grid's extent "
                f"({src.height}x{src.width}) at {terrain_grid_path}"
            )

        elevation = float(src.read(1)[row, col])
        slope_deg = float(src.read(2)[row, col])
        aspect_deg = float(src.read(3)[row, col])

    return elevation, slope_deg, aspect_deg


def generate_downscaled_field(
    regional_forecast: RegionalEnsembleForecast,
    site_id: str,
    site_lat: float,
    site_lon: float,
    terrain_grid_path: str,
    calibration_coeffs: dict,
    calibration_confidence: str,
) -> DownscaledForecastField:
    """Downscale every member/timestep of `regional_forecast` to the site
    at `(site_lat, site_lon)`, using terrain sampled from
    `terrain_grid_path` (T1B.3's output) and `calibration_coeffs` (T1B.6's
    output — genuinely fit or `IDENTITY_COEFFICIENTS`).

    `calibration_confidence` is passed through verbatim onto the returned
    `DownscaledForecastField` — this function doesn't recompute or
    second-guess it; T1B.5 already determined it honestly.

    Terrain is sampled once per call (the site's coordinates don't change
    per-member/per-timestep), then the same elevation/slope/aspect are
    used for every point in the ensemble — physically correct, since it's
    one physical location's terrain being downscaled against, not a
    spatially-varying field.
    """
    elevation_m, slope_deg, aspect_deg = _sample_terrain_at_site(
        terrain_grid_path, site_lat, site_lon
    )

    downscaled_members = []
    for member in regional_forecast.members:
        downscaled_trajectory = [
            DownscaledTimestepValue(
                hour=timestep.hour,
                inflow_mm=downscale_rainfall(
                    coarse_value_mm=timestep.rainfall_mm,
                    elevation_m=elevation_m,
                    slope_deg=slope_deg,
                    aspect_deg=aspect_deg,
                    calibration_coeffs=calibration_coeffs,
                ),
            )
            for timestep in member.trajectory
        ]
        downscaled_members.append(
            DownscaledEnsembleMember(
                member_id=member.member_id,
                trajectory=downscaled_trajectory,
            )
        )

    return DownscaledForecastField(
        site_id=site_id,
        site_lat=site_lat,
        site_lon=site_lon,
        calibration_confidence=calibration_confidence,
        source_forecast_id=regional_forecast.forecast_id,
        generated_at=datetime.now(timezone.utc),
        members=downscaled_members,
    )
