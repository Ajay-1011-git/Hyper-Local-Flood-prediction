"""Tests for the GEFS client (2026-08-20 amendment).

EXTERNAL NETWORK IS MOCKED throughout (T1A.12-style convention, matching
`test_cwc.py`/`test_wn2mini.py`'s own real-network-mocking discipline) --
none of these hit NOMADS live. The real live confirmation (real fetch,
real decode, real 31-member/12-timestep forecast) is documented in
`gefs/client.py`'s and `gefs/parser.py`'s module docstrings and this
task's commit message, not reproduced as a live-network test here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from stage1a.config import Stage1ASettings
from stage1a.gefs.client import _candidate_cycles, _fetch_one, _gefs_file_url, fetch_gefs_forecast
from stage1a.gefs.errors import GEFSParseError, GEFSUnavailableError
from stage1a.gefs.parser import GEFS_MEMBERS
from stage1a.shared.contracts import BoundingBox

TN_BBOX = BoundingBox(min_lat=8.0, max_lat=14.0, min_lon=76.0, max_lon=82.0)
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "gefs_sample_p01_f003.grib2"


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the retry backoff for every test in this file.

    The real delays (`_TRANSIENT_RETRY_DELAY_S`, exponentially backed off)
    are deliberately long enough to ride out a real NOMADS hiccup — which
    made this file alone take ~17s of pure `time.sleep`. The retry
    *logic* is what's under test here, not the wall-clock spacing, so the
    delay is zeroed rather than the retry count reduced (which would
    change the behaviour being tested).
    """
    import stage1a.gefs.client as client_module

    monkeypatch.setattr(client_module, "_TRANSIENT_RETRY_DELAY_S", 0.0)


# --------------------------------------------------------------- pure helpers


def test_candidate_cycles_floors_to_a_real_cycle_boundary() -> None:
    now = datetime(2026, 8, 20, 11, 17, tzinfo=timezone.utc)  # not itself a cycle hour
    candidates = _candidate_cycles(now, lag_hours=5.0, retries=0)
    assert candidates == [datetime(2026, 8, 20, 6, tzinfo=timezone.utc)]


def test_candidate_cycles_steps_back_six_hours_each_retry() -> None:
    now = datetime(2026, 8, 20, 11, 17, tzinfo=timezone.utc)
    candidates = _candidate_cycles(now, lag_hours=5.0, retries=2)
    assert candidates == [
        datetime(2026, 8, 20, 6, tzinfo=timezone.utc),
        datetime(2026, 8, 20, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 19, 18, tzinfo=timezone.utc),
    ]


def test_candidate_cycles_never_returns_a_future_cycle() -> None:
    now = datetime(2026, 8, 20, 0, 30, tzinfo=timezone.utc)  # just after 00Z
    candidates = _candidate_cycles(now, lag_hours=5.0, retries=0)
    # 00:30 - 5h = 19:30 the previous day -> floors to 18Z the previous day
    assert candidates == [datetime(2026, 8, 19, 18, tzinfo=timezone.utc)]


def test_s3_object_url_matches_the_real_confirmed_layout() -> None:
    from stage1a.gefs.client import _s3_object_url

    url = _s3_object_url(
        "https://noaa-gefs-pds.s3.amazonaws.com",
        datetime(2026, 8, 20, 6, tzinfo=timezone.utc), "p01", 12,
    )
    assert url == (
        "https://noaa-gefs-pds.s3.amazonaws.com/gefs.20260820/06/atmos/"
        "pgrb2sp25/gep01.t06z.pgrb2s.0p25.f012"
    )


#: Verbatim excerpt of a REAL `.idx` sidecar fetched live this session
#: (gefs.20260820/06, gep01, f012) -- record 18 is APCP:surface at byte
#: 8492791, and record 19 starts at 8779783.
_REAL_IDX_EXCERPT = """1:0:d=2026082006:VIS:surface:12 hour fcst:ENS=+1
17:7901844:d=2026082006:CPOFP:surface:12 hour fcst:ENS=+1
18:8492791:d=2026082006:APCP:surface:6-12 hour acc fcst:ENS=+1
19:8779783:d=2026082006:CSNOW:surface:6-12 hour ave fcst:ENS=+1
20:8798246:d=2026082006:CICEP:surface:6-12 hour ave fcst:ENS=+1"""


def test_parse_apcp_byte_range_from_a_real_idx() -> None:
    from stage1a.gefs.client import _parse_apcp_byte_range

    start, end = _parse_apcp_byte_range(_REAL_IDX_EXCERPT)
    assert start == 8492791
    assert end == 8779782  # next record's start - 1


def test_parse_apcp_byte_range_last_record_has_open_ended_range() -> None:
    from stage1a.gefs.client import _parse_apcp_byte_range

    start, end = _parse_apcp_byte_range(
        "1:0:d=2026082006:VIS:surface:12 hour fcst:ENS=+1\n"
        "2:500:d=2026082006:APCP:surface:6-12 hour acc fcst:ENS=+1"
    )
    assert start == 500
    assert end is None  # runs to end-of-file


def test_parse_apcp_byte_range_without_apcp_raises_typed_error() -> None:
    from stage1a.gefs.client import _parse_apcp_byte_range

    with pytest.raises(GEFSParseError):
        _parse_apcp_byte_range("1:0:d=2026082006:VIS:surface:12 hour fcst:ENS=+1")


def test_fetch_one_s3_uses_a_real_range_request() -> None:
    from stage1a.gefs.client import _fetch_one_s3

    grib_bytes = REAL_FIXTURE.read_bytes()
    captured: dict[str, object] = {}

    client = httpx.Client()

    def _fake_get(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith(".idx"):
            return httpx.Response(200, text=_REAL_IDX_EXCERPT)
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(206, content=grib_bytes)

    client.get = _fake_get  # type: ignore[assignment]
    result = _fetch_one_s3(
        client, "https://s3.test", datetime(2026, 8, 20, 6, tzinfo=timezone.utc),
        "p01", 12, 10.0,
    )
    assert result == grib_bytes
    assert captured["headers"] == {"Range": "bytes=8492791-8779782"}


def test_fetch_one_s3_missing_object_raises_unavailable() -> None:
    from stage1a.gefs.client import _fetch_one_s3

    client = _mock_client([httpx.Response(404, text="not found")])
    with pytest.raises(GEFSUnavailableError):
        _fetch_one_s3(
            client, "https://s3.test", datetime(2099, 1, 1, tzinfo=timezone.utc),
            "c00", 6, 10.0,
        )


def test_fetch_one_s3_network_error_on_idx_raises_unavailable_not_uncaught() -> None:
    """2026-08-20 regression test: a real network-level failure (not an
    HTTP response at all) on the .idx request must become
    GEFSUnavailableError, not propagate as a raw httpx exception --
    reproduced live against the real S3 transport this session
    (httpx.RemoteProtocolError), confirmed as a genuine bug before this
    fix (the status-code checks never saw it)."""
    from stage1a.gefs.client import _fetch_one_s3

    client = httpx.Client()
    client.get = MagicMock(side_effect=httpx.RemoteProtocolError("simulated: server disconnected"))  # type: ignore[method-assign]
    with pytest.raises(GEFSUnavailableError):
        _fetch_one_s3(
            client, "https://s3.test", datetime(2026, 8, 20, tzinfo=timezone.utc),
            "c00", 6, 10.0,
        )


def test_fetch_one_s3_network_error_on_range_request_raises_unavailable() -> None:
    """Same regression, but on the second (range) request rather than the
    .idx sidecar -- both call sites needed the fix independently."""
    from stage1a.gefs.client import _fetch_one_s3

    client = httpx.Client()
    client.get = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            httpx.Response(200, text=_REAL_IDX_EXCERPT),
            httpx.ReadTimeout("simulated: read timed out"),
        ]
    )
    with pytest.raises(GEFSUnavailableError):
        _fetch_one_s3(
            client, "https://s3.test", datetime(2026, 8, 20, tzinfo=timezone.utc),
            "c00", 6, 10.0,
        )


def test_transport_falls_back_to_nomads_when_s3_has_a_real_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The S3-network-error fix must actually reach _fetch_one_any_transport's
    existing fallback logic, not just raise GEFSUnavailableError in
    isolation -- an end-to-end check of the fix, not just the unit."""
    from stage1a.gefs.client import _fetch_one_any_transport

    grib_bytes = REAL_FIXTURE.read_bytes()

    def _fake_get(url: str, **kwargs: object) -> httpx.Response:
        if "s3.test" in url:
            raise httpx.ConnectError("simulated: connection refused")
        return httpx.Response(200, content=grib_bytes)

    client = httpx.Client()
    client.get = _fake_get  # type: ignore[assignment]
    settings = Stage1ASettings(gefs_s3_base_url="https://s3.test")

    result = _fetch_one_any_transport(
        client, settings, datetime(2026, 8, 20, 6, tzinfo=timezone.utc), "c00", 6, TN_BBOX,
    )
    assert result == grib_bytes


def test_transport_falls_back_to_nomads_when_s3_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3 unavailable must fall through to the NOMADS filter transport."""
    import stage1a.gefs.client as client_module
    from stage1a.gefs.client import _fetch_one_any_transport

    grib_bytes = REAL_FIXTURE.read_bytes()
    calls: list[str] = []

    def _s3_unavailable(*args: object, **kwargs: object) -> bytes:
        calls.append("s3")
        raise GEFSUnavailableError("simulated: S3 unreachable")

    def _nomads_ok(*args: object, **kwargs: object) -> bytes:
        calls.append("nomads")
        return grib_bytes

    monkeypatch.setattr(client_module, "_fetch_one_s3", _s3_unavailable)
    monkeypatch.setattr(client_module, "_fetch_one", _nomads_ok)

    result = _fetch_one_any_transport(
        httpx.Client(), Stage1ASettings(),
        datetime(2026, 8, 20, 6, tzinfo=timezone.utc), "c00", 6, TN_BBOX,
    )
    assert result == grib_bytes
    assert calls == ["s3", "nomads"]


def test_gefs_file_url_contains_real_confirmed_shape() -> None:
    cycle = datetime(2026, 8, 19, 0, tzinfo=timezone.utc)
    url = _gefs_file_url(
        "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p25s.pl",
        cycle, "p01", 3, TN_BBOX,
    )
    assert "file=gep01.t00z.pgrb2s.0p25.f003" in url
    assert "dir=/gefs.20260819/00/atmos/pgrb2sp25" in url
    assert "var_APCP=on" in url and "lev_surface=on" in url
    assert "leftlon=76.0" in url and "toplat=14.0" in url


# --------------------------------------------------------------- _fetch_one


def _mock_client(responses: list[httpx.Response | Exception]) -> httpx.Client:
    """A real `httpx.Client` whose `.get` is replaced with a canned
    sequence -- items may be real `Response`s or `Exception` instances
    (raised, matching `MagicMock(side_effect=...)`'s real behavior), for
    simulating network-level failures alongside HTTP responses."""
    client = httpx.Client()
    mock_get = MagicMock(side_effect=responses)
    client.get = mock_get  # type: ignore[method-assign]
    return client


def test_fetch_one_succeeds_on_real_grib_response() -> None:
    grib_bytes = REAL_FIXTURE.read_bytes()
    client = _mock_client([httpx.Response(200, content=grib_bytes)])
    result = _fetch_one(
        client, "https://example.test", datetime(2026, 8, 19, tzinfo=timezone.utc),
        "p01", 3, TN_BBOX, 10.0,
    )
    assert result == grib_bytes


def test_fetch_one_retries_then_succeeds() -> None:
    grib_bytes = REAL_FIXTURE.read_bytes()
    client = _mock_client([
        httpx.Response(302, content=b"<!doctype html>not real data"),
        httpx.Response(200, content=grib_bytes),
    ])
    result = _fetch_one(
        client, "https://example.test", datetime(2026, 8, 19, tzinfo=timezone.utc),
        "c00", 6, TN_BBOX, 10.0,
    )
    assert result == grib_bytes


def test_fetch_one_raises_unavailable_after_exhausting_retries() -> None:
    client = _mock_client([
        httpx.Response(403, content=b"Request for Future Data") for _ in range(10)
    ])
    with pytest.raises(GEFSUnavailableError):
        _fetch_one(
            client, "https://example.test", datetime(2099, 1, 1, tzinfo=timezone.utc),
            "c00", 6, TN_BBOX, 10.0,
        )


def test_fetch_one_retries_past_a_real_network_error() -> None:
    """2026-08-20 regression test: NOMADS's own transport has the same
    class of bug as S3's -- a real network-level failure (not an HTTP
    response) must be treated as just another transient attempt, not
    propagate uncaught."""
    grib_bytes = REAL_FIXTURE.read_bytes()
    client = _mock_client([
        httpx.ReadTimeout("simulated: read timed out"),
        httpx.Response(200, content=grib_bytes),
    ])
    result = _fetch_one(
        client, "https://example.test", datetime(2026, 8, 19, tzinfo=timezone.utc),
        "c00", 6, TN_BBOX, 10.0,
    )
    assert result == grib_bytes


def test_fetch_one_raises_unavailable_after_network_errors_exhaust_retries() -> None:
    client = _mock_client([
        httpx.ConnectError("simulated: connection refused") for _ in range(10)
    ])
    with pytest.raises(GEFSUnavailableError):
        _fetch_one(
            client, "https://example.test", datetime(2099, 1, 1, tzinfo=timezone.utc),
            "c00", 6, TN_BBOX, 10.0,
        )


# --------------------------------------------------------- fetch_gefs_forecast


def test_fetch_gefs_forecast_falls_through_when_no_cycle_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every candidate cycle unavailable -> GEFSUnavailableError, not a hang."""
    import stage1a.gefs.client as client_module

    def _always_unavailable(*args: object, **kwargs: object) -> bytes:
        raise GEFSUnavailableError("simulated: nothing published")

    monkeypatch.setattr(client_module, "_fetch_one_any_transport", _always_unavailable)
    settings = Stage1ASettings(gefs_cycle_retries=1, gefs_max_concurrent_requests=2)

    with pytest.raises(GEFSUnavailableError):
        fetch_gefs_forecast(TN_BBOX, datetime.now(timezone.utc), settings)


def test_fetch_gefs_forecast_builds_a_real_31_member_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end with every network call mocked: probe + all (member, hour) fetches succeed."""
    import stage1a.gefs.client as client_module

    call_count = {"n": 0}

    def _fake_fetch(
        client: object, settings: object, cycle: datetime, member: str,
        lead_hour: int, bbox: BoundingBox,
    ) -> bytes:
        call_count["n"] += 1
        return REAL_FIXTURE.read_bytes()

    monkeypatch.setattr(client_module, "_fetch_one_any_transport", _fake_fetch)
    settings = Stage1ASettings(gefs_cycle_retries=0, gefs_max_concurrent_requests=4)

    result = fetch_gefs_forecast(TN_BBOX, datetime.now(timezone.utc), settings)

    assert result.forecast.source == "GEFS"
    assert len(result.forecast.members) == len(GEFS_MEMBERS) == 31
    assert result.provenance.synthetic is False
    # 1 probe + 31 members * 12 real timesteps (6..72h step 6)
    assert call_count["n"] == 1 + 31 * 12
