"""Exposure scoring — T3.3.

`compute_exposure_score` quantifies "what's exposed" at a building or road
segment: presence/area/extent as the base signal, optionally weighted by
a real population density if the caller supplies one.

Per this stage's Operating Contract rule 1 — "Never fabricate a
population-density figure for the site. If no real population data
source is confirmed available, omit population from exposure entirely
rather than estimating it" — this module does NOT fetch or estimate
population data itself. No population data source has been confirmed or
connected anywhere in this project as of 2026-08-20 (there is no VIT
Vellore campus occupancy dataset wired into this pipeline). Callers pass
a real `population_density` value only if and when they have one; the
`None` default is the actual, current, honest state — not a placeholder
waiting to be filled with a guess.
"""

from __future__ import annotations

from typing import Optional, Union

from backend.stage3.shared.contracts import BuildingFootprint, RoadSegment

# A structure/segment that geometrically resolves to zero area/length
# (degenerate input) still counts as "exists" per this task's explicit
# requirement ("a building exists = nonzero exposure"). This floor value
# is a reasonable default, flagged like this project's other threshold
# constants — not independently verified as the "correct" minimum
# exposure unit, just a guarantee that presence alone never scores zero.
_MIN_PRESENCE_EXPOSURE = 1.0


class UnsupportedExposureTargetError(Exception):
    """Raised when `footprint_or_segment` is neither a BuildingFootprint
    nor a RoadSegment."""


def _polygon_area_m2(polygon: list[list[float]]) -> float:
    """Shoelace formula for a simple 2D polygon's area."""
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _polyline_length_m(polyline: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(polyline) - 1):
        x1, y1 = polyline[i]
        x2, y2 = polyline[i + 1]
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return total


def compute_exposure_score(
    footprint_or_segment: Union[BuildingFootprint, RoadSegment],
    population_density: Optional[float] = None,
) -> float:
    """Base exposure is a real, explainable geometric quantity:
      - `BuildingFootprint`: its footprint's real area, in m² (shoelace
        formula on `footprint_polygon`).
      - `RoadSegment`: its polyline's real length × `width_m` (an area,
        in m²) if `width_m` is known; otherwise just the length, in m
        (extent alone — NOT padded with an invented width, since that
        would itself be a fabricated figure).

    Floored at `_MIN_PRESENCE_EXPOSURE` so degenerate/zero geometry still
    registers as "exists," per this task's explicit requirement.

    If `population_density` is given (people per m² — the caller's
    responsibility to supply a real, confirmed value), the base is scaled
    by `(1 + population_density)`: a real weighting that (a) is
    continuous with the no-population case at density=0, (b) always
    increases the score as density increases, (c) never discards the
    area/presence signal even when population data happens to be
    available. This formula is a reasonable, human-reviewable design
    choice — not independently proven optimal — flagged the same way as
    this project's other judgment-call constants.

    Raises `UnsupportedExposureTargetError` for any other input type,
    `ValueError` for a negative `population_density` (not a real
    density).
    """
    if isinstance(footprint_or_segment, BuildingFootprint):
        base = _polygon_area_m2(footprint_or_segment.footprint_polygon)
    elif isinstance(footprint_or_segment, RoadSegment):
        length = _polyline_length_m(footprint_or_segment.polyline)
        base = (
            length * footprint_or_segment.width_m
            if footprint_or_segment.width_m is not None
            else length
        )
    else:
        raise UnsupportedExposureTargetError(
            f"compute_exposure_score expects a BuildingFootprint or "
            f"RoadSegment, got {type(footprint_or_segment)!r}"
        )

    base = max(base, _MIN_PRESENCE_EXPOSURE)

    if population_density is None:
        return base

    if population_density < 0:
        raise ValueError(
            f"population_density must be non-negative, got {population_density!r} "
            f"(a real density can't be negative — this isn't a place to pass a "
            f"placeholder/sentinel value; use None for 'no data' instead)"
        )

    return base * (1.0 + population_density)
