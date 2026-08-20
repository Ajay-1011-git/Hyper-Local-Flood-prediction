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


def test_forecast_id_is_namespaced() -> None:
    from stage1a.wn2mini.parser import build_forecast_id as wn2_id

    assert wn2_id(TN_BBOX, FORECAST_START).startswith("wn2mini-")


# --------------------------------------------------------- full chain (T1A.4)
#
# 2026-08-20 amendment: GEFS is now real (see gefs/client.py) and tried
# first, so every chain test below must simulate "GEFS unavailable" to
# reach and test the WN2 Mini fallback path deterministically -- without
# this, these tests would make real live NOMADS network calls (against
# T1A.12's own "mock all external network calls in automated tests"
# rule) and their outcome would depend on live GEFS availability rather
# than the WN2/chain logic actually under test. The old
# `test_gefs_always_raises_unavailable` (testing the pre-amendment stub
# that always raised) no longer applies -- GEFS's real behavior is
# covered in tests/test_gefs_client.py and tests/test_gefs_parser.py
# instead.


def _settings_with_wn2_path(path: object) -> Stage1ASettings:
    return Stage1ASettings(wn2_mini_forecast_path=path)  # type: ignore[arg-type]


def _simulate_gefs_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import stage1a.forecast.fallback as fallback_module
    from stage1a.gefs.errors import GEFSUnavailableError

    def _raise(*args: object, **kwargs: object) -> None:
        raise GEFSUnavailableError("simulated: GEFS unavailable for this test")

    monkeypatch.setattr(fallback_module, "fetch_gefs_forecast", _raise)


@requires_real_wn2_file
def test_chain_serves_wn2_mini_when_gefs_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from stage1a.forecast.fallback import get_regional_forecast
    from stage1a.forecast.provenance import ForecastPath

    _simulate_gefs_unavailable(monkeypatch)
    result = get_regional_forecast(
        TN_BBOX, FORECAST_START, _settings_with_wn2_path(REAL_FILE)
    )
    assert result.provenance.path is ForecastPath.WN2_MINI
    assert result.provenance.synthetic is False
    assert result.forecast.source == "WeatherNext2_Cyclones_Mini"


def test_chain_raises_when_nothing_is_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GenCast was removed outright -- GEFS down + WN2 Mini missing means nothing is left."""
    from stage1a.forecast.errors import NoRegionalForecastAvailableError
    from stage1a.forecast.fallback import get_regional_forecast

    _simulate_gefs_unavailable(monkeypatch)
    settings = Stage1ASettings(wn2_mini_forecast_path=tmp_path / "no_such_file.nc")
    with pytest.raises(NoRegionalForecastAvailableError):
        get_regional_forecast(TN_BBOX, FORECAST_START, settings)


def test_wn2_parse_errors_are_not_masked_by_the_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed WN2 file must surface as WN2ParseError, not fall through."""
    from stage1a.forecast.fallback import get_regional_forecast
    from stage1a.wn2mini.errors import WN2ParseError

    _simulate_gefs_unavailable(monkeypatch)
    path = tmp_path / "broken.nc"
    wn2_shaped_dataset(num_members=3).to_netcdf(path, engine="h5netcdf")

    with pytest.raises(WN2ParseError):
        get_regional_forecast(TN_BBOX, FORECAST_START, _settings_with_wn2_path(path))


@requires_real_wn2_file
def test_chain_prefers_gefs_over_wn2_mini_when_both_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-08-20 amendment: GEFS is now primary. With both sources
    mocked/present as available, GEFS must win -- WN2 Mini is never even
    attempted (its file existing is irrelevant to the outcome here)."""
    import stage1a.forecast.fallback as fallback_module
    from stage1a.forecast.fallback import get_regional_forecast
    from stage1a.forecast.provenance import ForecastPath, ForecastProvenance, RegionalForecastResult
    from stage1a.gefs.parser import build_regional_ensemble_forecast, GEFS_MEMBERS
    from datetime import datetime as dt, timezone as tz

    fake_forecast = build_regional_ensemble_forecast(
        {m: {6: 1.0} for m in GEFS_MEMBERS}, TN_BBOX, FORECAST_START
    )
    fake_result = RegionalForecastResult(
        forecast=fake_forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.GEFS, retrieved_at=dt.now(tz.utc), synthetic=False
        ),
    )
    monkeypatch.setattr(fallback_module, "fetch_gefs_forecast", lambda *a, **k: fake_result)

    result = get_regional_forecast(
        TN_BBOX, FORECAST_START, _settings_with_wn2_path(REAL_FILE)
    )
    assert result.provenance.path is ForecastPath.GEFS
    assert result.forecast.source == "GEFS"
