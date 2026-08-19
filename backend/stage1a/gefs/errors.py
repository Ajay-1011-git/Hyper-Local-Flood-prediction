"""Typed errors for the (unimplemented) GEFS path."""

from __future__ import annotations


class GEFSError(RuntimeError):
    """Base class for GEFS-path failures."""


class GEFSUnavailableError(GEFSError):
    """GEFS integration is not implemented, or could not be reached.

    Always raised by `client.fetch_gefs_forecast` today — see the module
    docstring in `gefs/__init__.py`.
    """
