"""Typed errors for the GEFS path (real as of the 2026-08-20 amendment)."""

from __future__ import annotations


class GEFSError(RuntimeError):
    """Base class for GEFS-path failures."""


class GEFSUnavailableError(GEFSError):
    """No real GEFS cycle could be reached/found for the requested window.

    Raised after exhausting `GEFS_CYCLE_RETRIES` candidate cycles (each
    stepped 6h further back) against NOMADS's real "Request for Future
    Data" / not-yet-published signal — never fabricated in its place.
    """


class GEFSParseError(GEFSError):
    """A fetched GEFS GRIB2 response could not be decoded into the expected shape.

    Raised instead of silently substituting a default/placeholder value —
    a malformed or unexpected response is a real bug to surface, not a
    reason to fall through to WeatherNext 2 Mini (mirrors WN2ParseError's
    own "not caught in fallback.py" convention).
    """
