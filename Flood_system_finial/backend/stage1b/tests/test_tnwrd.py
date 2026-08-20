"""Tests for T1B.4 — TN WRD rainfall telemetry client.

External HTTP is mocked here (per T1B.12's convention). The real live
fetch — real CKAN package_show call, real 3-resource CSV download,
174,311 real normalized rows, a real Vellore-district station found
("Gollapally") — was run manually during development; see
tnwrd/client.py's module docstring and the task's commit message for that
VERIFY output.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pandas as pd
import pytest

from backend.stage1b.tnwrd.client import (
    TnwrdApiError,
    TnwrdDownloadError,
    TnwrdNoResourcesFoundError,
    _dataset_slug_from_url,
    fetch_rainfall_telemetry,
)

_REAL_HEADER = (
    "SlNo,Station,Agency,State LGD Code,State,District LGD Code,District,"
    "Tehsil,Block,Village,River,Basin,Tributary,Subtributary,SubSubtributary,"
    "Local River,Latitude,Longitude,Data Acquisition Time,"
    "Telemetry Hourly Rainfall (mm)"
)


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text or str(json_body)

    def json(self):
        return self._json_body


def _fake_csv_text(rows: list[str]) -> str:
    return "\n".join([_REAL_HEADER] + rows) + "\n"


def test_dataset_slug_from_url():
    assert (
        _dataset_slug_from_url(
            "https://nwdp.nwic.gov.in/dataset/rainfall-telemetry-hourly-tamil-nadu-sw-gw"
        )
        == "rainfall-telemetry-hourly-tamil-nadu-sw-gw"
    )


def test_fetch_raises_tnwrd_api_error_on_failed_request():
    with patch(
        "backend.stage1b.tnwrd.client.requests.get",
        side_effect=[_FakeResponse(500, text="server error")],
    ):
        with pytest.raises(TnwrdApiError):
            fetch_rainfall_telemetry()


def test_fetch_raises_when_no_csv_resources():
    with patch(
        "backend.stage1b.tnwrd.client.requests.get",
        return_value=_FakeResponse(
            200, {"success": True, "result": {"resources": [{"format": "PDF", "url": "x"}]}}
        ),
    ):
        with pytest.raises(TnwrdNoResourcesFoundError):
            fetch_rainfall_telemetry()


def test_fetch_raises_when_resource_missing_expected_columns():
    bad_csv = "A,B,C\n1,2,3\n"

    def fake_get(url, **kwargs):
        if "package_show" in url:
            return _FakeResponse(
                200,
                {
                    "success": True,
                    "result": {
                        "resources": [
                            {"name": "bad", "format": "CSV", "url": "http://x/bad.csv"}
                        ]
                    },
                },
            )
        raise AssertionError(f"unexpected GET {url}")

    # Built before patching: pd.read_csv gets patched below, and patching
    # the same attribute the test helper itself would call causes infinite
    # recursion (a real gotcha, not theoretical — caught by running this).
    bad_df = pd.read_csv(io.StringIO(bad_csv), dtype=str)

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch(
            "backend.stage1b.tnwrd.client.pd.read_csv", return_value=bad_df
        ):
            with pytest.raises(TnwrdDownloadError):
                fetch_rainfall_telemetry()


def test_fetch_rainfall_telemetry_normalizes_real_shaped_rows():
    csv_text = _fake_csv_text(
        [
            "1,Gollapally,Tamil Nadu SW GW,33,Tamil Nadu,595,Vellore,Gudiyatham,-,-,-,-,-,-,-,-,"
            "13.03194444,78.86444444,12-01-2026 03:00,0.5",
            "2,Anaikidangu,Tamil Nadu SW GW,33,Tamil Nadu,575,Kanyakumari,-,-,-,-,-,-,-,-,-,"
            "8.23470000,77.37789400,21-02-2026 16:00,10.5",
        ]
    )

    def fake_get(url, **kwargs):
        assert "package_show" in url
        return _FakeResponse(
            200,
            {
                "success": True,
                "result": {
                    "resources": [
                        {
                            "name": "2026-2030",
                            "format": "CSV",
                            "url": "http://fake/rainfall.csv",
                        }
                    ]
                },
            },
        )

    parsed_df = pd.read_csv(io.StringIO(csv_text), dtype=str)

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch(
            "backend.stage1b.tnwrd.client.pd.read_csv", return_value=parsed_df
        ):
            df = fetch_rainfall_telemetry()

    assert list(df.columns) == [
        "station_id",
        "station_name",
        "district",
        "latitude",
        "longitude",
        "timestamp",
        "rainfall_mm",
    ]
    assert len(df) == 2

    gollapally = df[df["station_id"] == "Gollapally"].iloc[0]
    assert gollapally["district"] == "Vellore"
    assert gollapally["latitude"] == pytest.approx(13.03194444)
    assert gollapally["longitude"] == pytest.approx(78.86444444)
    assert gollapally["rainfall_mm"] == pytest.approx(0.5)
    assert str(gollapally["timestamp"]) == "2026-01-12 03:00:00"


def test_fetch_deduplicates_across_resources():
    row = (
        "1,Gollapally,Tamil Nadu SW GW,33,Tamil Nadu,595,Vellore,Gudiyatham,-,-,-,-,-,-,-,-,"
        "13.03194444,78.86444444,12-01-2026 03:00,0.5"
    )
    csv_text = _fake_csv_text([row])

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        return _FakeResponse(
            200,
            {
                "success": True,
                "result": {
                    "resources": [
                        {"name": "a", "format": "CSV", "url": "http://fake/a.csv"},
                        {"name": "b", "format": "CSV", "url": "http://fake/b.csv"},
                    ]
                },
            },
        )

    parsed_df = pd.read_csv(io.StringIO(csv_text), dtype=str)

    def fake_read_csv(url, **kwargs):
        call_count["n"] += 1
        return parsed_df

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch("backend.stage1b.tnwrd.client.pd.read_csv", side_effect=fake_read_csv):
            df = fetch_rainfall_telemetry()

    assert call_count["n"] == 2  # both resources were fetched
    assert len(df) == 1  # but the identical row was deduplicated


# --------------------------------------------------------------- caching
# (2026-08-20 addition -- see fetch_rainfall_telemetry's docstring for why
# the cache exists: the real fetch is ~24MB / 174,340 rows / ~16-17s
# measured live, not the "cheap" the old routes.py call site claimed.)


def _single_resource_mocks(call_count: dict):
    """Mocks for one real-shaped CSV resource, counting real downloads."""
    csv_text = _fake_csv_text(
        [
            "1,Vellore,Tamil Nadu SW GW,33,Tamil Nadu,595,Vellore,-,-,-,-,-,-,-,-,-,"
            "12.94861100,79.13888900,05-01-2026 12:20,1.0",
        ]
    )
    parsed_df = pd.read_csv(io.StringIO(csv_text), dtype=str)

    def fake_get(url, **kwargs):
        return _FakeResponse(
            200,
            {
                "success": True,
                "result": {
                    "resources": [
                        {"name": "2026-2030", "format": "CSV", "url": "http://fake/a.csv"}
                    ]
                },
            },
        )

    def fake_read_csv(url, **kwargs):
        call_count["n"] += 1
        return parsed_df

    return fake_get, fake_read_csv


def test_second_fetch_is_served_from_cache_without_redownloading():
    call_count = {"n": 0}
    fake_get, fake_read_csv = _single_resource_mocks(call_count)

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch("backend.stage1b.tnwrd.client.pd.read_csv", side_effect=fake_read_csv):
            first = fetch_rainfall_telemetry()
            second = fetch_rainfall_telemetry()

    assert call_count["n"] == 1  # the real download happened exactly once
    assert first is second  # same object, not merely equal


def test_force_refresh_bypasses_the_cache():
    call_count = {"n": 0}
    fake_get, fake_read_csv = _single_resource_mocks(call_count)

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch("backend.stage1b.tnwrd.client.pd.read_csv", side_effect=fake_read_csv):
            fetch_rainfall_telemetry()
            fetch_rainfall_telemetry(force_refresh=True)

    assert call_count["n"] == 2


def test_expired_cache_entry_is_refetched(monkeypatch: pytest.MonkeyPatch):
    """A stale entry must not be served past its TTL -- the whole point of
    a TTL rather than a permanent memo, since the upstream dataset really
    does update hourly."""
    import backend.stage1b.tnwrd.client as client_module

    call_count = {"n": 0}
    fake_get, fake_read_csv = _single_resource_mocks(call_count)
    monkeypatch.setattr(client_module, "TELEMETRY_CACHE_TTL_S", 0.0)

    with patch("backend.stage1b.tnwrd.client.requests.get", side_effect=fake_get):
        with patch("backend.stage1b.tnwrd.client.pd.read_csv", side_effect=fake_read_csv):
            fetch_rainfall_telemetry()
            fetch_rainfall_telemetry()

    assert call_count["n"] == 2
