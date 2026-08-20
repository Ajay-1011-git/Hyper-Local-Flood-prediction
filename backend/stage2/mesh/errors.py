"""Typed errors for computational mesh assembly (T2.4)."""

from __future__ import annotations


class MeshAssemblyError(RuntimeError):
    """Base class for computational-mesh assembly failures."""


class DoubleTaggedNodeError(MeshAssemblyError):
    """A grid cell's position falls inside more than one building's footprint.

    Raised instead of silently picking one — footprints shouldn't overlap
    for real, physically separate buildings; if they do, that's a real
    problem with T2.3's output (or T2.1's source mesh) worth surfacing,
    not resolving arbitrarily.
    """
