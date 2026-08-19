"""Typed errors for the WeatherNext 2 Mini ingestion path."""

from __future__ import annotations


class WN2Error(RuntimeError):
    """Base class for every WeatherNext 2 Mini ingestion failure."""


class WN2ForecastUnavailableError(WN2Error):
    """No usable WN2 Mini `.nc` file exists at the configured path.

    Raised instead of fabricating data. Triggers the next link in
    `fallback.get_regional_forecast`'s chain.
    """


class WN2ParseError(WN2Error):
    """The `.nc` file's structure does not match what was confirmed.

    Raised when a required contract field cannot be populated — never
    filled with a placeholder.
    """
