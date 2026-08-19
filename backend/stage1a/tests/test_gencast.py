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


# ------------------------------------------------------------------- T1A.3


def test_parser_produces_a_valid_contract_object() -> None:
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.shared.contracts import RegionalEnsembleForecast
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    forecast = parse_gencast_output(
        synthetic_gencast_dataset(num_members=3), VELLORE_BBOX, FORECAST_START
    )
    assert isinstance(forecast, RegionalEnsembleForecast)
    assert forecast.source == "GenCast"
    assert len(forecast.members) == 3
    assert [t.hour for t in forecast.members[0].trajectory] == [12, 24, 36, 48, 60, 72]


def test_forecast_id_is_deterministic_across_reparses() -> None:
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    first = parse_gencast_output(
        synthetic_gencast_dataset(), VELLORE_BBOX, FORECAST_START
    )
    second = parse_gencast_output(
        synthetic_gencast_dataset(), VELLORE_BBOX, FORECAST_START
    )
    assert first.forecast_id == second.forecast_id


def test_forecast_id_changes_with_window_and_region() -> None:
    from datetime import timedelta

    from stage1a.gencast.parser import build_forecast_id

    base = build_forecast_id(VELLORE_BBOX, FORECAST_START)
    later = build_forecast_id(VELLORE_BBOX, FORECAST_START + timedelta(hours=12))
    elsewhere = build_forecast_id(
        BoundingBox(min_lat=0.0, max_lat=1.0, min_lon=0.0, max_lon=1.0), FORECAST_START
    )
    assert len({base, later, elsewhere}) == 3


def test_forecast_id_is_timezone_normalised() -> None:
    from datetime import timedelta, timezone as tz

    from stage1a.gencast.parser import build_forecast_id

    ist = FORECAST_START.astimezone(tz(timedelta(hours=5, minutes=30)))
    assert build_forecast_id(VELLORE_BBOX, ist) == build_forecast_id(
        VELLORE_BBOX, FORECAST_START
    )


def test_metres_are_converted_to_millimetres() -> None:
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    in_m = parse_gencast_output(
        synthetic_gencast_dataset(units="m"), VELLORE_BBOX, FORECAST_START
    )
    in_mm = parse_gencast_output(
        synthetic_gencast_dataset(units="mm"), VELLORE_BBOX, FORECAST_START
    )
    assert in_m.members[0].trajectory[0].rainfall_mm == pytest.approx(
        in_mm.members[0].trajectory[0].rainfall_mm * 1000.0
    )


def test_missing_units_is_an_error_not_a_guess() -> None:
    from stage1a.gencast.errors import GenCastParseError
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    with pytest.raises(GenCastParseError, match="units"):
        parse_gencast_output(
            synthetic_gencast_dataset(units=None), VELLORE_BBOX, FORECAST_START
        )


def test_absolute_and_relative_time_coords_agree() -> None:
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    relative = parse_gencast_output(
        synthetic_gencast_dataset(use_absolute_time=False), VELLORE_BBOX, FORECAST_START
    )
    absolute = parse_gencast_output(
        synthetic_gencast_dataset(use_absolute_time=True), VELLORE_BBOX, FORECAST_START
    )
    assert [t.hour for t in relative.members[0].trajectory] == [
        t.hour for t in absolute.members[0].trajectory
    ]


def test_bbox_with_no_grid_cells_is_an_error() -> None:
    from stage1a.gencast.errors import GenCastParseError
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    with pytest.raises(GenCastParseError, match="No GenCast grid cells"):
        parse_gencast_output(
            synthetic_gencast_dataset(),
            BoundingBox(min_lat=-40.0, max_lat=-39.0, min_lon=10.0, max_lon=11.0),
            FORECAST_START,
        )


def test_missing_precipitation_variable_is_an_error() -> None:
    from stage1a.gencast.errors import GenCastParseError
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    dataset = synthetic_gencast_dataset().rename({"total_precipitation_12hr": "wrong"})
    with pytest.raises(GenCastParseError, match="total_precipitation_12hr"):
        parse_gencast_output(dataset, VELLORE_BBOX, FORECAST_START)


def test_non_finite_values_are_rejected() -> None:
    import numpy as np

    from stage1a.gencast.errors import GenCastParseError
    from stage1a.gencast.parser import parse_gencast_output
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    dataset = synthetic_gencast_dataset()
    dataset["total_precipitation_12hr"].values[:] = np.nan
    with pytest.raises(GenCastParseError):
        parse_gencast_output(dataset, VELLORE_BBOX, FORECAST_START)
