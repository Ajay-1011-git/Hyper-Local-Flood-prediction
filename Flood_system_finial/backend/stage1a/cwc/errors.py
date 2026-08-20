"""Typed errors for the CWC / National Water Data Portal client."""

from __future__ import annotations


class CWCError(RuntimeError):
    """Base class for every CWC data-access failure."""


class CWCUnavailableError(CWCError):
    """The National Water Data Portal could not be reached or returned an error.

    Raised on network failure or a non-success CKAN response — never
    swallowed to return an empty or fabricated station list.
    """


class CWCParseError(CWCError):
    """A CKAN response could not be mapped onto the expected shape."""
