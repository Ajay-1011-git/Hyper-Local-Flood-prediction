"""Tests for T1B.2 — Bhuvan (Bhoonidhi) DEM client.

External HTTP calls are mocked here (matches T1B.12's requirement to mock
Bhuvan/TN WRD in the automated suite) — the *real* live call against the
Bhoonidhi API, with a real account, was run manually during development;
see dem/client.py's module docstring for that VERIFY output (real
access_token, real 401 on bad creds, real 4-feature search result, real
47MB ZIP containing a real GeoTIFF, confirmed valid with rasterio).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from backend.shared.contracts import BoundingBox
from backend.stage1b.dem.client import (
    BhoonidhiAuthError,
    BhoonidhiCredentialsMissingError,
    DemDownloadError,
    DemNotFoundError,
    fetch_dem_raster,
)


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, content: bytes = b"", text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.content = content
        self.text = text or (str(json_body) if json_body is not None else "")

    def json(self):
        return self._json_body


def _make_fake_tif_bytes(min_lon=79.0, min_lat=12.9, max_lon=80.0, max_lat=13.9) -> bytes:
    """Build a tiny real GeoTIFF in memory (not a placeholder blob) so the
    zip-extraction / rasterio-open path is exercised against real raster
    bytes, same as production would see."""
    data = np.linspace(0, 500, 4 * 4, dtype="float32").reshape(4, 4)
    transform = from_bounds(min_lon, min_lat, max_lon, max_lat, 4, 4)
    buf = io.BytesIO()
    with rasterio.open(
        buf,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


def _make_fake_download_zip(tile_id: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{tile_id}/{tile_id}_DEM_30m.tif", _make_fake_tif_bytes())
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _configure_credentials(monkeypatch):
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.bhoonidhi_user_id", "test_user"
    )
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.bhoonidhi_password", "test_pass"
    )
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.bhoonidhi_dem_collection",
        "CartoSat-1_PAN_CartoDEM_30m",
    )


@pytest.fixture
def _bbox():
    return BoundingBox(min_lat=12.9, max_lat=13.0, min_lon=79.1, max_lon=79.2)


def test_fetch_dem_raster_raises_when_credentials_missing(monkeypatch, _bbox, tmp_path):
    monkeypatch.setattr("backend.stage1b.dem.client.settings.bhoonidhi_user_id", None)
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.dem_raster_storage_dir", str(tmp_path)
    )
    with pytest.raises(BhoonidhiCredentialsMissingError):
        fetch_dem_raster(_bbox)


def test_fetch_dem_raster_raises_on_auth_rejection(monkeypatch, _bbox, tmp_path):
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.dem_raster_storage_dir", str(tmp_path)
    )

    def fake_post(url, **kwargs):
        assert url.endswith("/auth/token")
        return _FakeResponse(
            401,
            {
                "ErrorCode": "401",
                "Description": "Invalid Credentials!",
                "Action": "Please enter correct userId and password",
            },
        )

    with patch("backend.stage1b.dem.client.requests.post", side_effect=fake_post):
        with pytest.raises(BhoonidhiAuthError, match="401"):
            fetch_dem_raster(_bbox)


def test_fetch_dem_raster_raises_when_no_online_tiles(monkeypatch, _bbox, tmp_path):
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.dem_raster_storage_dir", str(tmp_path)
    )

    def fake_post(url, **kwargs):
        if url.endswith("/auth/token"):
            return _FakeResponse(200, {"access_token": "fake-token"})
        if url.endswith("/data/search"):
            return _FakeResponse(
                200,
                {
                    "context": {"limit": 50, "returned": 1},
                    "features": [
                        {
                            "id": "P5_PAN_CD_N12_000_E079_000_30m",
                            "collection": "CartoSat-1_PAN_CartoDEM_30m",
                            "properties": {"Online": "N"},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected POST {url}")

    with patch("backend.stage1b.dem.client.requests.post", side_effect=fake_post):
        with pytest.raises(DemNotFoundError):
            fetch_dem_raster(_bbox)


def test_fetch_dem_raster_success_single_tile(monkeypatch, _bbox, tmp_path):
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.dem_raster_storage_dir", str(tmp_path)
    )
    tile_id = "P5_PAN_CD_N12_000_E079_000_30m"

    def fake_post(url, **kwargs):
        if url.endswith("/auth/token"):
            return _FakeResponse(200, {"access_token": "fake-token"})
        if url.endswith("/data/search"):
            return _FakeResponse(
                200,
                {
                    "context": {"limit": 50, "returned": 1},
                    "features": [
                        {
                            "id": tile_id,
                            "collection": "CartoSat-1_PAN_CartoDEM_30m",
                            "properties": {"Online": "Y"},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        assert url.endswith("/download")
        assert kwargs["params"] == {
            "id": tile_id,
            "collection": "CartoSat-1_PAN_CartoDEM_30m",
        }
        return _FakeResponse(200, content=_make_fake_download_zip(tile_id))

    with patch("backend.stage1b.dem.client.requests.post", side_effect=fake_post), patch(
        "backend.stage1b.dem.client.requests.get", side_effect=fake_get
    ):
        path = fetch_dem_raster(_bbox)

    assert Path(path).exists()
    with rasterio.open(path) as src:
        assert src.crs is not None
        assert src.shape == (4, 4)


def test_fetch_dem_raster_raises_on_bad_zip(monkeypatch, _bbox, tmp_path):
    monkeypatch.setattr(
        "backend.stage1b.dem.client.settings.dem_raster_storage_dir", str(tmp_path)
    )
    tile_id = "P5_PAN_CD_N12_000_E079_000_30m"

    def fake_post(url, **kwargs):
        if url.endswith("/auth/token"):
            return _FakeResponse(200, {"access_token": "fake-token"})
        if url.endswith("/data/search"):
            return _FakeResponse(
                200,
                {
                    "features": [
                        {
                            "id": tile_id,
                            "collection": "CartoSat-1_PAN_CartoDEM_30m",
                            "properties": {"Online": "Y"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        return _FakeResponse(200, content=b"not a zip file")

    with patch("backend.stage1b.dem.client.requests.post", side_effect=fake_post), patch(
        "backend.stage1b.dem.client.requests.get", side_effect=fake_get
    ):
        with pytest.raises(DemDownloadError):
            fetch_dem_raster(_bbox)
