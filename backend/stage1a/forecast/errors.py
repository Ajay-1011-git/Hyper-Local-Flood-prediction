"""Typed errors for the regional forecast acquisition chain."""

from __future__ import annotations


class RegionalForecastError(RuntimeError):
    """Base class for every regional-forecast-acquisition failure."""


class NoRegionalForecastAvailableError(RegionalForecastError):
    """Every source in the chain was tried and none produced a forecast.

    Raised instead of returning fabricated data — see `fallback.py`.
    """
