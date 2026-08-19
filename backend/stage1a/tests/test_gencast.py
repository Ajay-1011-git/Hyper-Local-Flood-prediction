"""Tests for the GenCast path (T1A.2-T1A.5)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stage1a.config import Stage1ASettings
from stage1a.gencast.client import check_gencast_available, run_gencast_inference
from stage1a.gencast.errors import GenCastUnavailableError
from stage1a.shared.contracts import BoundingBox

VELLORE_BBOX = BoundingBox(min_lat=12.5, max_lat=13.3, min_lon=78.8, max_lon=79.5)
FORECAST_START = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)


def _settings(**overrides: object) -> Stage1ASettings:
    return Stage1ASettings(**overrides)  # type: ignore[arg-type]


# ------------------------------------------------------------------- T1A.2


def test_unavailable_when_weights_unconfigured() -> None:
    """No weights and no endpoint -> a typed error naming what is missing."""
    with pytest.raises(GenCastUnavailableError) as exc:
        check_gencast_available(
            _settings(gencast_weights_path=None, gencast_tpu_endpoint=None)
        )
    assert "GENCAST_WEIGHTS_PATH" in str(exc.value)


def test_unavailable_error_names_every_missing_dependency() -> None:
    """The message must be diagnosable, not opaque."""
    with pytest.raises(GenCastUnavailableError) as exc:
        check_gencast_available(_settings())
    message = str(exc.value)
    assert "weathernext" in message
    assert "jax" in message
    # It must point at the fallback rather than inviting a synthesised result.
    assert "fallback" in message.lower()


def test_run_gencast_inference_raises_rather_than_fabricating() -> None:
    """The unimplemented seam must surface, never return a plausible Dataset."""
    with pytest.raises(GenCastUnavailableError):
        run_gencast_inference(
            VELLORE_BBOX,
            FORECAST_START,
            settings=_settings(gencast_weights_path="/some/weights.npz"),
        )


def test_error_is_not_swallowed_by_the_public_entry_point() -> None:
    """`run_gencast_inference` must propagate, not catch-and-default."""
    with pytest.raises(GenCastUnavailableError):
        run_gencast_inference(VELLORE_BBOX, FORECAST_START, settings=_settings())
