"""Typed errors for Stage 2's terrain layer (T2.2/T2.3)."""

from __future__ import annotations


class TerrainError(RuntimeError):
    """Base class for terrain-generation failures."""


class Stage1BTerrainUnavailableError(TerrainError):
    """No Stage 1B `dem_metadata` row covers the requested site bounding box.

    Raised instead of fabricating a terrain grid. T1B.2/T1B.3 must have
    actually run for the target region first.
    """


class AmbiguousNorthAxisError(TerrainError):
    """`AnchorPoint.north_axis` is not one of the axis-aligned values this
    session can confidently convert (`+X`/`-X`/`+Y`/`-Y`).

    CLAUDE.md rule 4: if orientation is missing or ambiguous, stop and ask
    rather than assume the GLB's default axes are geographically aligned.
    An arbitrary rotation would need more than a single axis label to
    resolve correctly.
    """
