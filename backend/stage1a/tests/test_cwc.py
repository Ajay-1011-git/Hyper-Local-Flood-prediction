"""Tests for the CWC / National Water Data Portal client (T1A.6)."""

from __future__ import annotations

import pytest

from stage1a.cwc.client import KNOWN_RELEVANT_RESOURCES, fetch_station_data, fetch_station_list
from stage1a.cwc.errors import CWCUnavailableError
from stage1a.tests.conftest import requires_live_network

#: These three tests make REAL calls to the National Water Data Portal.
#: They are kept (they're genuine, and they're the only thing that proves
#: the real CWC integration still works), but are now OPT-IN rather than
#: "run whenever the portal happens to be reachable" — they dominated the
#: default suite's runtime (~2 min) and their result depended on a
#: government portal's live availability rather than on this code. See
#: `tests/conftest.py`'s `requires_live_network` for the rationale and how
#: to run them (`RUN_LIVE_NETWORK_TESTS=1 pytest tests/`).
requires_live_portal = requires_live_network


def test_known_resources_are_documented() -> None:
    """Every hardcoded resource must carry its provenance, not a bare id."""
    assert len(KNOWN_RELEVANT_RESOURCES) >= 1
    for resource in KNOWN_RELEVANT_RESOURCES:
        assert resource.resource_id
        assert resource.label
        assert resource.agency


def test_unreachable_host_raises_typed_error() -> None:
    from stage1a.config import Stage1ASettings

    settings = Stage1ASettings(
        cwc_data_portal_base_url="https://this-host-does-not-exist.invalid"
    )
    with pytest.raises(CWCUnavailableError):
        fetch_station_list(settings)


@requires_live_portal
def test_fetch_station_list_returns_real_stations_with_coordinates() -> None:
    stations = fetch_station_list()
    assert len(stations) > 0
    for station in stations:
        assert isinstance(station["lat"], float)
        assert isinstance(station["lon"], float)
        assert -90.0 <= station["lat"] <= 90.0
        assert -180.0 <= station["lon"] <= 180.0
        assert station["station_id"]
        assert station["resource_id"]


@requires_live_portal
def test_fetch_station_data_returns_real_readings() -> None:
    stations = fetch_station_list()
    station = stations[0]
    records = fetch_station_data(station, hours=5)
    assert len(records) > 0
    for record in records:
        assert record.get("Station") == station["station_id"]
        assert "River Water Level Telemetry Hourly (meter)" in record


@requires_live_portal
def test_no_duplicate_stations_across_resources() -> None:
    """Same station name in two different resources must not collide."""
    stations = fetch_station_list()
    keys = [(s["resource_id"], s["station_id"]) for s in stations]
    assert len(keys) == len(set(keys))
