"""Typed errors for the GenCast path (T1A.2-T1A.5).

Kept in their own module so `client.py`, `parser.py`, `fallback.py` and
`tasks.py` can all import them without importing each other.
"""

from __future__ import annotations


class GenCastError(RuntimeError):
    """Base class for every GenCast-path failure."""


class GenCastUnavailableError(GenCastError):
    """Live GenCast inference cannot run in this environment.

    Raised instead of returning fabricated data. The correct response is
    T1A.4's precomputed fallback, not a synthesised forecast.
    """


class GenCastParseError(GenCastError):
    """GenCast's raw output could not be mapped onto `RegionalEnsembleForecast`.

    Raised when a required contract field cannot be populated from the raw
    output — never filled with a placeholder.
    """


class NoFallbackAvailableError(GenCastError):
    """No precomputed forecast exists for the requested window."""
