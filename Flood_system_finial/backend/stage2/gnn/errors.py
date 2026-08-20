"""Typed errors for T2.6's GNN model."""

from __future__ import annotations


class GNNError(RuntimeError):
    """Base class for GNN model failures."""


class InsufficientHistoryError(GNNError):
    """Fewer than `previous_t` timesteps of history are available to build model input.

    Raised instead of zero-padding or otherwise fabricating history the
    model was never trained to expect.
    """
