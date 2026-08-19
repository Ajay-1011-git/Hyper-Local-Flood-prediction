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


# ------------------------------------------------------------------- T1A.4


def _settings_with_dir(directory: object) -> Stage1ASettings:
    """Settings isolating the legacy GenCast pair from the chain amendment.

    These T1A.4 tests target `load_precomputed_forecast`/`load_precomputed_result`/
    `get_regional_forecast`'s original live-inference/synthetic-fallback pair
    directly, not the full GEFS -> WN2 Mini -> legacy chain added later
    (tests/test_wn2mini.py covers that chain). wn2_mini_forecast_path is
    pointed at a location that cannot exist, so `get_regional_forecast`
    reaches the legacy pair exactly as these tests expect, regardless of
    whether a real WN2 export happens to be present on this machine.
    """
    return _settings(
        gencast_precomputed_fallback_dir=directory,
        wn2_mini_forecast_path="/nonexistent/stage1a-test-isolation/no_wn2_file.nc",
    )


def test_fallback_raises_when_no_precomputed_file_exists(tmp_path: object) -> None:
    from stage1a.gencast.errors import NoFallbackAvailableError
    from stage1a.gencast.fallback import load_precomputed_forecast

    with pytest.raises(NoFallbackAvailableError):
        load_precomputed_forecast(
            VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
        )


def test_get_regional_forecast_falls_back_and_marks_the_path(tmp_path: object) -> None:
    from stage1a.gencast.devdata import write_placeholder
    from stage1a.gencast.fallback import get_regional_forecast
    from stage1a.gencast.provenance import ForecastPath

    write_placeholder(VELLORE_BBOX, FORECAST_START, num_members=4, directory=tmp_path)  # type: ignore[arg-type]

    result = get_regional_forecast(
        VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
    )
    assert result.provenance.path is ForecastPath.FALLBACK
    assert result.provenance.fallback_reason
    assert len(result.forecast.members) == 4


def test_placeholder_data_is_reported_as_synthetic(tmp_path: object) -> None:
    """A placeholder must never look like real model output downstream."""
    from stage1a.gencast.devdata import write_placeholder
    from stage1a.gencast.fallback import get_regional_forecast

    write_placeholder(VELLORE_BBOX, FORECAST_START, num_members=2, directory=tmp_path)  # type: ignore[arg-type]
    result = get_regional_forecast(
        VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
    )
    assert result.provenance.synthetic is True


def test_real_forecast_without_synthetic_stamp_is_not_flagged(tmp_path: object) -> None:
    """Dropping in genuine GenCast output flips `synthetic` to false, no code change."""
    from pathlib import Path

    from stage1a.gencast.fallback import get_regional_forecast
    from stage1a.gencast.parser import build_forecast_id
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    dataset = synthetic_gencast_dataset(num_members=2)
    del dataset.attrs["synthetic"]  # as a real Colab-produced file would be
    path = Path(str(tmp_path)) / f"{build_forecast_id(VELLORE_BBOX, FORECAST_START)}.nc"
    dataset.to_netcdf(path, engine="h5netcdf")

    result = get_regional_forecast(
        VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
    )
    assert result.provenance.synthetic is False


def test_fallback_matches_by_attributes_when_filename_differs(tmp_path: object) -> None:
    from pathlib import Path

    from stage1a.gencast.fallback import load_precomputed_forecast
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    path = Path(str(tmp_path)) / "some-other-name.nc"
    synthetic_gencast_dataset(num_members=2).to_netcdf(path, engine="h5netcdf")

    forecast = load_precomputed_forecast(
        VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
    )
    assert len(forecast.members) == 2


def test_wrong_window_is_not_silently_substituted(tmp_path: object) -> None:
    """A file for a different window must not be served for this one."""
    from datetime import timedelta

    from stage1a.gencast.devdata import write_placeholder
    from stage1a.gencast.errors import NoFallbackAvailableError
    from stage1a.gencast.fallback import load_precomputed_forecast

    write_placeholder(VELLORE_BBOX, FORECAST_START, num_members=2, directory=tmp_path)  # type: ignore[arg-type]

    with pytest.raises(NoFallbackAvailableError):
        load_precomputed_forecast(
            VELLORE_BBOX,
            FORECAST_START + timedelta(days=3),
            _settings_with_dir(tmp_path),
        )


def test_parse_errors_are_not_masked_by_the_fallback(tmp_path: object) -> None:
    """Only GenCastUnavailableError triggers fallback; a bad file must surface."""
    from pathlib import Path

    from stage1a.gencast.errors import GenCastParseError
    from stage1a.gencast.fallback import get_regional_forecast
    from stage1a.gencast.parser import build_forecast_id
    from stage1a.tests.fixtures import synthetic_gencast_dataset

    dataset = synthetic_gencast_dataset(num_members=2, units=None)
    path = Path(str(tmp_path)) / f"{build_forecast_id(VELLORE_BBOX, FORECAST_START)}.nc"
    dataset.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(GenCastParseError):
        get_regional_forecast(
            VELLORE_BBOX, FORECAST_START, _settings_with_dir(tmp_path)
        )


# ------------------------------------------------------------------- T1A.5


def test_task_survives_repeated_runs_on_fresh_event_loops() -> None:
    """Each Celery task uses a new loop; connections must not leak across them."""
    from stage1a.gencast.tasks import run_task_coroutine

    async def _probe() -> int:
        from stage1a.db import get_redis_client

        client = get_redis_client()
        await client.ping()
        return 1

    from stage1a.tests.conftest import _redis_reachable

    if not _redis_reachable():
        pytest.skip("Redis not reachable")

    assert run_task_coroutine(_probe()) == 1
    assert run_task_coroutine(_probe()) == 1  # would raise before the loop fix


def test_cache_ttl_matches_the_forecast_window() -> None:
    from stage1a.gencast.parser import FORECAST_HORIZON_HOURS
    from stage1a.gencast.tasks import CACHE_TTL

    assert CACHE_TTL.total_seconds() == FORECAST_HORIZON_HOURS * 3600


def test_cache_keys_are_derived_from_forecast_id() -> None:
    """Keys must be a pure function of forecast_id, or re-runs would accumulate."""
    from stage1a.gencast.tasks import forecast_cache_key, provenance_cache_key

    assert forecast_cache_key("abc") == forecast_cache_key("abc")
    assert forecast_cache_key("abc") != forecast_cache_key("def")
    assert provenance_cache_key("abc") != forecast_cache_key("abc")
