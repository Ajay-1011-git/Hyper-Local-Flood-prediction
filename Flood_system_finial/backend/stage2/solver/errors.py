"""Typed errors for the numerical shallow-water solver (T2.5)."""

from __future__ import annotations


class SolverError(RuntimeError):
    """Base class for shallow-water solver failures."""


class SolverInstabilityError(SolverError):
    """The solver produced a non-finite or unphysical (negative) depth.

    Raised instead of silently clamping/continuing — an unstable run means
    the timestep or parameters need adjusting, not a result to trust.
    """
