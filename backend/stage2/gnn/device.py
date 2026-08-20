"""Device resolution for T2.6 (Mac MPS, per the 2026-08-20 amendment).

API CONFIRMED IN-SESSION (not assumed): `torch.backends.mps.is_available()`
and `torch.backends.mps.is_built()` were both checked directly against the
installed PyTorch 2.13.0 on this machine and both returned `True`. This is
the current, real API for MPS device detection in this PyTorch version —
not recalled from memory.
"""

from __future__ import annotations

import logging
import os

import torch

logger = logging.getLogger(__name__)

# Per the amendment: any PyG operation without a Metal kernel should fall
# back to CPU rather than crash the run. Set before any MPS tensor op.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def resolve_device(preference: str | None = None) -> torch.device:
    """Return the device to train/infer on.

    `preference` defaults to `Stage2Settings.torch_device_preference`
    (`TORCH_DEVICE_PREFERENCE` in `.env`, `"mps"` by default) if not given
    explicitly. `"mps"` uses Apple Silicon's Metal backend if actually
    available on this machine, falling back to CPU otherwise. Per the
    amendment: this is a legitimate, explicitly-noted fallback, not a
    silent one — callers should log/report which device was actually
    used, not just which was requested.
    """
    if preference is None:
        from stage2.config import get_settings

        preference = get_settings().torch_device_preference
    if preference == "mps" and torch.backends.mps.is_available():
        return torch.device("mps")
    if preference == "mps":
        logger.warning(
            "MPS requested but not available on this machine "
            "(torch.backends.mps.is_available() = False); using CPU."
        )
    return torch.device("cpu")
