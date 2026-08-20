"""Typed errors for GLB/site-model ingestion."""

from __future__ import annotations


class IngestionError(RuntimeError):
    """Base class for site-model ingestion failures."""


class MissingSceneObjectError(IngestionError):
    """One or more expected named objects are absent from the GLB.

    Raised instead of silently proceeding with a partial building set —
    the exact required names are fixed by the Blender task's naming
    convention (CLAUDE.md ground truth), never fuzzy-matched.
    """


class InvalidAnchorPointError(IngestionError):
    """`anchor_point.json` is missing, malformed, or fails contract validation."""
