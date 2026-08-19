"""Tests for WeatherNext 2 Mini ingestion and the full source chain (amendment)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from stage1a.config import Stage1ASettings
from stage1a.shared.contracts import BoundingBox

TN_BBOX = BoundingBox(min_lat=8.0, max_lat=14.0, min_lon=76.0, max_lon=82.0)
FORECAST_START = datetime(2026, 8, 19, tzinfo=timezone.utc)

REAL_FILE = Path(__file__).resolve().parents[1] / "data" / "wn2_mini" / "tn_flood_forecast.nc"

requires_real_wn2_file = pytest.mark.skipif(
    not REAL_FILE.is_file(),
    reason="Real WN2 Mini export not present at data/wn2_mini/tn_flood_forecast.nc",
)


def wn2_shaped_dataset(
    *,
    num_members: int = 8,
    lead_hours: tuple[int, ...] = tuple(range(6, 121, 6)),
    include_batch_dim: bool = True,
    include_units: bool = False,
) -> xr.Dataset:
    """Build a dataset matching the REAL confirmed WN2 Mini structure.

    Mirrors, field-for-field, what direct inspection of the actual
    Colab-produced tn_flood_forecast.nc showed: dims (sample, time, batch,
    lat, lon), no `units` attr, no global attrs, timedelta64 `time`.
    """
    lats = np.arange(8.0, 15.0, 1.0)
    lons = np.arange(76.0, 83.0, 1.0)
    shape = (num_members, len(lead_hours), 1, len(lats), len(lons))
    rng = np.random.default_rng(42)
    values = rng.gamma(1.5, 0.004, size=shape).astype(np.float32)

    dims = ["sample", "time", "batch", "lat", "lon"]
    coords: dict[str, object] = {
        "sample": np.arange(num_members),
        "time": np.array([np.timedelta64(h, "h") for h in lead_hours], dtype="timedelta64[ns]"),
        "lat": lats.astype(np.float32),
        "lon": lons.astype(np.float32),
    }
    if not include_batch_dim:
        dims = ["sample", "time", "lat", "lon"]
        values = values[:, :, 0, :, :]

    attrs = {"units": "m"} if include_units else {}
    precip = xr.DataArray(values, dims=dims, coords=coords, attrs=attrs)
    return xr.Dataset({"total_precipitation_6hr": precip})


# ------------------------------------------------------------------- loader


def test_missing_file_raises_typed_error(tmp_path: Path) -> None:
    from stage1a.wn2mini.errors import WN2ForecastUnavailableError
    from stage1a.wn2mini.loader import load_wn2_mini_forecast

    with pytest.raises(WN2ForecastUnavailableError):
        load_wn2_mini_forecast(tmp_path / "missing.nc")


@requires_real_wn2_file
def test_loader_opens_the_real_file() -> None:
    from stage1a.wn2mini.loader import load_wn2_mini_forecast

    dataset = load_wn2_mini_forecast(REAL_FILE)
    assert dataset.sizes["sample"] == 8
    assert dataset.sizes["time"] == 20
    assert "total_precipitation_6hr" in dataset.data_vars


# ------------------------------------------------------------------- parser


@requires_real_wn2_file
def test_parses_the_real_file_into_a_valid_contract() -> None:
    from stage1a.wn2mini.loader import load_wn2_mini_forecast
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    dataset = load_wn2_mini_forecast(REAL_FILE)
    forecast = parse_wn2_mini_output(dataset, TN_BBOX, FORECAST_START)

    assert forecast.source == "WeatherNext2_Cyclones_Mini"
    assert forecast.resolution_km == 111.0
    assert len(forecast.members) == 8
    hours = [t.hour for t in forecast.members[0].trajectory]
    assert hours[0] == 6
    assert max(hours) >= 72
    assert all(h % 6 == 0 for h in hours)


def test_parses_a_wn2_shaped_fixture() -> None:
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    forecast = parse_wn2_mini_output(wn2_shaped_dataset(), TN_BBOX, FORECAST_START)
    assert len(forecast.members) == 8
    assert forecast.members[0].trajectory[0].hour == 6


def test_batch_dim_of_size_one_is_squeezed() -> None:
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    with_batch = parse_wn2_mini_output(
        wn2_shaped_dataset(include_batch_dim=True), TN_BBOX, FORECAST_START
    )
    without_batch = parse_wn2_mini_output(
        wn2_shaped_dataset(include_batch_dim=False), TN_BBOX, FORECAST_START
    )
    assert with_batch.model_dump() == without_batch.model_dump()


def test_wrong_member_count_is_a_typed_error() -> None:
    from stage1a.wn2mini.errors import WN2ParseError
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    with pytest.raises(WN2ParseError, match="expected exactly 8"):
        parse_wn2_mini_output(
            wn2_shaped_dataset(num_members=4), TN_BBOX, FORECAST_START
        )


def test_missing_units_assumes_metres_but_present_units_are_honoured() -> None:
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    no_units = parse_wn2_mini_output(
        wn2_shaped_dataset(include_units=False), TN_BBOX, FORECAST_START
    )
    with_units_m = parse_wn2_mini_output(
        wn2_shaped_dataset(include_units=True), TN_BBOX, FORECAST_START
    )
    assert no_units.model_dump() == with_units_m.model_dump()


def test_forecast_start_is_mandatory() -> None:
    """Unlike GenCast's parser, there is no attrs fallback — the real file has none."""
    import inspect

    from stage1a.wn2mini.parser import parse_wn2_mini_output

    params = inspect.signature(parse_wn2_mini_output).parameters
    assert params["forecast_start"].default is inspect.Parameter.empty


def test_negative_near_zero_rainfall_is_clamped_not_rejected() -> None:
    from stage1a.wn2mini.parser import parse_wn2_mini_output

    dataset = wn2_shaped_dataset(num_members=8)
    dataset["total_precipitation_6hr"].values[0, 0, 0, 0, 0] = -1.3e-5
    forecast = parse_wn2_mini_output(dataset, TN_BBOX, FORECAST_START)
    assert all(
        t.rainfall_mm >= 0.0
        for member in forecast.members
        for t in member.trajectory
    )


def test_forecast_id_is_namespaced_separately_from_gencast() -> None:
    from stage1a.gencast.parser import build_forecast_id as gencast_id
    from stage1a.wn2mini.parser import build_forecast_id as wn2_id

    assert wn2_id(TN_BBOX, FORECAST_START).startswith("wn2mini-")
    assert gencast_id(TN_BBOX, FORECAST_START).startswith("gencast-")
    assert wn2_id(TN_BBOX, FORECAST_START) != gencast_id(TN_BBOX, FORECAST_START)


# -------------------------------------------------------------- gefs stub


def test_gefs_always_raises_unavailable() -> None:
    from stage1a.gefs.client import fetch_gefs_forecast
    from stage1a.gefs.errors import GEFSUnavailableError

    with pytest.raises(GEFSUnavailableError):
        fetch_gefs_forecast(TN_BBOX, FORECAST_START)


# --------------------------------------------------------- full chain (T1A.4)


def _settings_with_wn2_path(path: object) -> Stage1ASettings:
    return Stage1ASettings(wn2_mini_forecast_path=path)  # type: ignore[arg-type]


@requires_real_wn2_file
def test_chain_serves_wn2_mini_when_present() -> None:
    from stage1a.gencast.fallback import get_regional_forecast
    from stage1a.gencast.provenance import ForecastPath

    result = get_regional_forecast(
        TN_BBOX, FORECAST_START, _settings_with_wn2_path(REAL_FILE)
    )
    assert result.provenance.path is ForecastPath.WN2_MINI
    assert result.provenance.synthetic is False
    assert result.forecast.source == "WeatherNext2_Cyclones_Mini"


def test_chain_falls_through_to_legacy_gencast_when_wn2_missing(tmp_path: Path) -> None:
    from stage1a.gencast.devdata import write_placeholder
    from stage1a.gencast.fallback import get_regional_forecast
    from stage1a.gencast.provenance import ForecastPath

    gencast_dir = tmp_path / "gencast_fallback"
    write_placeholder(TN_BBOX, FORECAST_START, num_members=5, directory=gencast_dir)

    settings = Stage1ASettings(
        wn2_mini_forecast_path=tmp_path / "no_such_file.nc",
        gencast_precomputed_fallback_dir=gencast_dir,
    )
    result = get_regional_forecast(TN_BBOX, FORECAST_START, settings)
    assert result.provenance.path is ForecastPath.FALLBACK
    assert result.forecast.source == "GenCast"


def test_chain_raises_when_nothing_is_available(tmp_path: Path) -> None:
    from stage1a.gencast.errors import NoFallbackAvailableError
    from stage1a.gencast.fallback import get_regional_forecast

    settings = Stage1ASettings(
        wn2_mini_forecast_path=tmp_path / "no_such_file.nc",
        gencast_precomputed_fallback_dir=tmp_path / "empty_gencast_dir",
    )
    with pytest.raises(NoFallbackAvailableError):
        get_regional_forecast(TN_BBOX, FORECAST_START, settings)


def test_wn2_parse_errors_are_not_masked_by_the_chain(tmp_path: Path) -> None:
    """A malformed WN2 file must surface as WN2ParseError, not fall through."""
    from stage1a.wn2mini.errors import WN2ParseError

    path = tmp_path / "broken.nc"
    wn2_shaped_dataset(num_members=3).to_netcdf(path, engine="h5netcdf")

    from stage1a.gencast.fallback import get_regional_forecast

    with pytest.raises(WN2ParseError):
        get_regional_forecast(TN_BBOX, FORECAST_START, _settings_with_wn2_path(path))
