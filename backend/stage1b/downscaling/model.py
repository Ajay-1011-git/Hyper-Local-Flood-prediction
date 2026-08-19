"""Terrain-based statistical downscaling model core — T1B.7.

Applies the exact formula T1B.6's `fit_calibration` fits coefficients for
(see calibration.py's module docstring for the full derivation/rationale):

    adjusted_mm = coarse_mm * (
        1
        + elevation_factor_per_1000m * (elevation_m - reference_elevation_m) / 1000
        + slope_factor_per_45deg * slope_deg / 45
        + aspect_cos_factor * cos(radians(aspect_deg))
        + aspect_sin_factor * sin(radians(aspect_deg))
    ) + intercept_mm

`calibration_coeffs` is whatever `fit_calibration` (or
`IDENTITY_COEFFICIENTS` for the honest no-op path) returned — this
function doesn't care whether individual terrain factors were genuinely
fit or forced to 0.0 for being unidentifiable; it just applies whatever
coefficients it's given. With `IDENTITY_COEFFICIENTS` every factor and
the intercept are 0.0, so `adjusted_mm == coarse_mm` exactly — the
downscaling model correctly becomes a pass-through when no real
calibration was possible.

Deterministic by construction: pure arithmetic on the given inputs, no
randomness, no I/O, no mutable module state — required by the project's
idempotency quality gate (T1B.8's orchestration re-running the same
regional forecast for the same site must produce the same downscaled
field every time).
"""

from __future__ import annotations

import math


def downscale_rainfall(
    coarse_value_mm: float,
    elevation_m: float,
    slope_deg: float,
    aspect_deg: float,
    calibration_coeffs: dict,
) -> float:
    """Apply the terrain-adjustment formula to one coarse rainfall value at
    one point, given its elevation/slope/aspect and a coefficients dict
    from `calibration.fit_calibration` (or `IDENTITY_COEFFICIENTS`).

    Rainfall cannot be physically negative, so the result is clamped to
    `>= 0.0` — a real, deliberate physical constraint (the raw formula can
    go negative for a large negative intercept combined with a small
    coarse value), not a silent behavior change: this is documented here,
    not something a caller could be surprised by.
    """
    reference_elevation_m = calibration_coeffs["reference_elevation_m"]
    aspect_rad = math.radians(aspect_deg)

    adjustment_factor = (
        1.0
        + calibration_coeffs["elevation_factor_per_1000m"]
        * (elevation_m - reference_elevation_m)
        / 1000.0
        + calibration_coeffs["slope_factor_per_45deg"] * slope_deg / 45.0
        + calibration_coeffs["aspect_cos_factor"] * math.cos(aspect_rad)
        + calibration_coeffs["aspect_sin_factor"] * math.sin(aspect_rad)
    )

    adjusted_mm = coarse_value_mm * adjustment_factor + calibration_coeffs["intercept_mm"]
    return max(0.0, adjusted_mm)
