"""Calibration fitting — T1B.6.

Per the project's Architecture doc §2.3 ("Hyperlocal downscaling to 2km
resolution"): the downscaling method is "terrain-based statistical
downscaling" from the named family of "cascade-based orographic
downscaling, the Froude Number Method, elevation-based precipitation
adjustment factors," and calibration works by comparing "historical
periods where both a TN WRD gauge reading and a corresponding GenCast
forecast exist"; "systematic gaps between the model's computed estimate
and the gauge's actual measurement become a correction term applied to
the downscaling parameters." No exact formula is mandated there, so this
implements the named "elevation-based precipitation adjustment factors"
technique as a linear correction on top of the coarse regional estimate:

    adjusted_mm = coarse_mm * (
        1
        + elevation_factor_per_1000m * (elevation_m - reference_elevation_m) / 1000
        + slope_factor_per_45deg * slope_deg / 45
        + aspect_cos_factor * cos(radians(aspect_deg))
        + aspect_sin_factor * sin(radians(aspect_deg))
    ) + intercept_mm

The cos/sin aspect pair (rather than a single directional term) lets the
fit find whichever effective "prevailing exposure direction" the real
calibration data supports, without this code assuming a specific monsoon
wind direction that isn't in any input contract (`RegionalEnsembleForecast`
carries rainfall only, no wind field). `fit_calibration` finds these five
coefficients by ordinary least squares against real matched (observed,
coarse-estimate, elevation, slope, aspect) samples — it does not invent
a formula that "should" be true, it fits one from data. T1B.7 applies this
formula's math; this task only fits its coefficients.

IMPORTANT — data availability at time of writing: Stage 1A (which
produces `RegionalEnsembleForecast`, the source of the *coarse* side of
this comparison) is being built independently by a different team member
and has no historical archive available in this repo yet. Real matched
(TN WRD gauge, GenCast coarse estimate) pairs therefore don't exist to
fit against right now. Per the project's own explicit allowance for this
exact situation (T1B.8's docstring: "for development before Stage 1A's
endpoint exists, use a mock fixture, clearly labeled as such, not a
fabricated 'real' call"), the VERIFY step for this task uses T1B.4/T1B.5's
REAL TN WRD 'Vellore' station historical readings as the observed side,
paired with a CLEARLY LABELED SYNTHETIC coarse-estimate fixture (real
observed value plus a known synthetic elevation-dependent bias + noise)
standing in for the not-yet-available real GenCast historical archive —
never presented as real GenCast output.
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np

logger = logging.getLogger(__name__)

# Below this many matched samples, a least-squares fit for 5 coefficients
# is underdetermined/unreliable rather than genuinely calibrated. Flagged
# as an unverified default for human review, same pattern as this
# project's other unreviewed thresholds (station-proximity, etc.) — not a
# statistically proven-correct minimum for this specific dataset.
MIN_CALIBRATION_SAMPLES = 20

IDENTITY_COEFFICIENTS = {
    "elevation_factor_per_1000m": 0.0,
    "slope_factor_per_45deg": 0.0,
    "aspect_cos_factor": 0.0,
    "aspect_sin_factor": 0.0,
    "intercept_mm": 0.0,
    "reference_elevation_m": 0.0,
    "n_samples": 0,
    "unidentifiable_terrain_parameters": [
        "elevation_factor_per_1000m",
        "slope_factor_per_45deg",
        "aspect_cos_factor",
        "aspect_sin_factor",
    ],
}


def fit_calibration(
    historical_tnwrd_readings: Sequence[float],
    historical_regional_estimates: Sequence[float],
    elevation_m: Sequence[float],
    slope_deg: Sequence[float],
    aspect_deg: Sequence[float],
    calibration_confidence: str,
) -> dict:
    """Fit the elevation/slope/aspect correction coefficients described in
    this module's docstring against matched calibration samples.

    All five sequence arguments must be the same length — one entry per
    matched (real TN WRD reading, coarse regional estimate at that same
    time/place, terrain values at that place) sample.

    If `calibration_confidence` is `"computed_only_no_nearby_station"`
    (T1B.5's honest no-nearby-station signal) or there are fewer than
    `MIN_CALIBRATION_SAMPLES` matched samples, this returns
    `IDENTITY_COEFFICIENTS` (all zero factors, zero intercept) — i.e. the
    downscaling model becomes a no-op pass-through of the coarse estimate
    — and logs why, rather than fabricating a correction from data that
    doesn't support one.
    """
    if calibration_confidence != "calibrated_nearby_station":
        logger.warning(
            "fit_calibration: calibration_confidence=%r (not "
            "'calibrated_nearby_station') — returning identity/no-op "
            "coefficients, no real calibration is possible without a "
            "nearby station.",
            calibration_confidence,
        )
        return dict(IDENTITY_COEFFICIENTS)

    n = len(historical_tnwrd_readings)
    if not (
        n
        == len(historical_regional_estimates)
        == len(elevation_m)
        == len(slope_deg)
        == len(aspect_deg)
    ):
        raise ValueError(
            "fit_calibration: all input sequences must have equal length "
            f"(got {n}, {len(historical_regional_estimates)}, "
            f"{len(elevation_m)}, {len(slope_deg)}, {len(aspect_deg)})"
        )

    if n < MIN_CALIBRATION_SAMPLES:
        logger.warning(
            "fit_calibration: only %d matched samples (< "
            "MIN_CALIBRATION_SAMPLES=%d) — returning identity/no-op "
            "coefficients rather than an unreliable fit.",
            n,
            MIN_CALIBRATION_SAMPLES,
        )
        return dict(IDENTITY_COEFFICIENTS)

    observed = np.asarray(historical_tnwrd_readings, dtype=np.float64)
    coarse = np.asarray(historical_regional_estimates, dtype=np.float64)
    elevation = np.asarray(elevation_m, dtype=np.float64)
    slope = np.asarray(slope_deg, dtype=np.float64)
    aspect_rad = np.radians(np.asarray(aspect_deg, dtype=np.float64))

    reference_elevation_m = float(np.mean(elevation))
    residual = observed - coarse

    candidate_columns = {
        "elevation_factor_per_1000m": coarse * (elevation - reference_elevation_m) / 1000.0,
        "slope_factor_per_45deg": coarse * (slope / 45.0),
        "aspect_cos_factor": coarse * np.cos(aspect_rad),
        "aspect_sin_factor": coarse * np.sin(aspect_rad),
    }

    # A terrain feature that's (near-)constant across every calibration
    # sample cannot have its coefficient identified by least squares — e.g.
    # calibrating against a single station's time series means every
    # sample shares that one station's elevation/slope/aspect. The check
    # MUST be on the raw terrain value's variance, not the coarse-scaled
    # design column's: `coarse * constant_slope` still has nonzero
    # variance (because coarse varies), which would wrongly look
    # "identifiable" — but it's then exactly proportional to every other
    # coarse-scaled constant-terrain column (aspect_cos, aspect_sin all
    # become scalar multiples of the same `coarse` vector), so they're
    # collinear with EACH OTHER even though no single column is literally
    # all-zero. Checking raw-value variance catches this; checking the
    # scaled column's variance (an earlier version of this function) did
    # not — caught by actually running this against the real single-
    # station calibration case below, not from inspection alone.
    _NEAR_ZERO_STD = 1e-9
    raw_terrain_std = {
        "elevation_factor_per_1000m": np.std(elevation),
        "slope_factor_per_45deg": np.std(slope),
        # aspect's own std isn't meaningful directly (it's a circular
        # quantity), so use its cos/sin components — if the aspect value
        # is constant, both are constant too.
        "aspect_cos_factor": np.std(np.cos(aspect_rad)),
        "aspect_sin_factor": np.std(np.sin(aspect_rad)),
    }
    identifiable = {
        name: col
        for name, col in candidate_columns.items()
        if raw_terrain_std[name] > _NEAR_ZERO_STD
    }
    unidentifiable = [name for name in candidate_columns if name not in identifiable]
    if unidentifiable:
        logger.warning(
            "fit_calibration: %s not identifiable from this calibration "
            "data (the underlying terrain value has ~zero variance across "
            "the %d matched samples — likely because they all come from "
            "one station; calibrating these requires samples spanning "
            "multiple stations at different elevations/slopes/aspects). "
            "Fixed at 0.0 rather than fit; only fields not in "
            "'unidentifiable_terrain_parameters' were genuinely regressed.",
            unidentifiable,
            n,
        )

    ordered_names = list(identifiable.keys())
    design = np.column_stack(
        [identifiable[name] for name in ordered_names] + [np.ones(n)]
    )

    fit_coeffs, _residuals, _rank, _sv = np.linalg.lstsq(design, residual, rcond=None)
    intercept_mm = float(fit_coeffs[-1])

    result = dict(IDENTITY_COEFFICIENTS)
    result["intercept_mm"] = intercept_mm
    result["reference_elevation_m"] = reference_elevation_m
    result["n_samples"] = n
    result["unidentifiable_terrain_parameters"] = unidentifiable
    for name, coeff in zip(ordered_names, fit_coeffs[:-1]):
        result[name] = float(coeff)

    return result
