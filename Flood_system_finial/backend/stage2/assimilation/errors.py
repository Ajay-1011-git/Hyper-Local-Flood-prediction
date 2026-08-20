"""Typed errors for live sensor assimilation (T2.8)."""

from __future__ import annotations


class AssimilationError(RuntimeError):
    """Base class for live sensor assimilation failures."""


class SensorLocationNotConfiguredError(AssimilationError):
    """The physical sensor's mesh position/mount height isn't configured yet.

    Raised instead of guessing a location: as of this writing the hardware
    unit has not been physically placed (confirmed with the project
    owner), so there is no real position to assimilate against. T2.9's
    route surfaces this as a clear error rather than silently picking an
    arbitrary node.
    """


class SensorAtWallNodeError(AssimilationError):
    """The configured/nearest node is a wall (building) node.

    Buildings are genuine no-flow obstacles (CLAUDE.md ground truth) —
    assimilating a water depth into one would corrupt that invariant, so
    this is refused rather than silently applied.
    """
