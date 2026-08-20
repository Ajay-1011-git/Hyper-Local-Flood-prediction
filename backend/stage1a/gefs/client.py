"""GEFS forecast client — REAL, live, primary source (2026-08-20 amendment).

TWO REAL TRANSPORTS: S3 PRIMARY, NOMADS FALLBACK
---------------------------------------------------------------------
Both were fetched and exercised directly in this session (not read from
documentation alone), and the priority between them is a real, measured
decision, not a preference:

1. **PRIMARY — NOAA Open Data Dissemination on S3** (no rate limiting):

       GET {s3_base}/gefs.{YYYYMMDD}/{HH}/atmos/pgrb2sp25/
           ge{member}.t{HH}z.pgrb2s.0p25.f{hour:03d}[.idx]

   The `.idx` sidecar lists every GRIB record's start byte, so only the
   `APCP:surface` record is downloaded, via an HTTP `Range:` request.
   Confirmed live: a real HTTP 206 returning 286,992 bytes in 1.73s,
   decoding to the real global 0.25deg field (721x1440) whose Tamil Nadu
   subset is the same 25x25 grid NOMADS returns server-side.

2. **FALLBACK — NOMADS GRIB-filter CGI** (server-side subsetting):

       GET {filter_base}?file=ge{member}.t{cycle}z.pgrb2s.0p25.f{hour:03d}
           &var_APCP=on&lev_surface=on
           &subregion=&leftlon=..&rightlon=..&toplat=..&bottomlat=..
           &dir=/gefs.{YYYYMMDD}/{cycle}/atmos/pgrb2sp25

   Confirmed live: a real 988-byte single-variable GRIB2 subset (cycle
   2026-08-19 00Z, p01, f003), and an HTTP 403 "Request for Future Data"
   page for an unpublished cycle.

WHY S3 IS PRIMARY DESPITE BEING ~380x MORE BANDWIDTH PER RECORD
---------------------------------------------------------------------
NOMADS's filter service is a shared, rate-limited government CGI. A real
full-cycle fetch here is 31 members x 12 lead hours = 372 requests, and
running that repeatedly this session caused NOMADS to start load-shedding
(HTTP 302 to an HTML error page, and long stalls) on requests that had
succeeded moments earlier for the identical URL — which cost GEFS the
fallback chain entirely and silently handed it to WeatherNext 2 Mini.
S3 has no such limit. The cost is real and stated honestly: ~287KB per
record (the global APCP field, since S3 cannot subset server-side) vs
NOMADS's ~750 bytes, i.e. roughly 107MB per full cycle fetch instead of
~280KB. That runs out-of-band in Celery once per 6-hour cycle (TRD §4:
"heavy computation must never happen on the request path"), so the
bandwidth is affordable and the reliability is what matters. NOMADS is
kept as a genuine fallback for when S3 itself is unreachable.

The real member list was confirmed via `GRIB_totalNumber: 30` on a
perturbation member's own GRIB metadata (see `parser.py`'s module
docstring for the full decode confirmation).

WHY THIS SOURCE IS TRIED FIRST (unchanged from the pre-existing chain
order, now made real): GEFS is fully automated, no manual step, unlike
WeatherNext 2 Mini's Colab-export requirement — see
`forecast/fallback.py`'s module docstring.

CYCLE DISCOVERY, NOT A FIXED SCHEDULE
---------------------------------------------------------------------
`forecast_start` (the caller's "now") rarely lines up with an actually-
published cycle (published every 6h with a real publication lag —
`Stage1ASettings.gefs_publication_lag_hours`). This module floors
`forecast_start - lag` to the most recent {00,06,12,18}Z boundary, then
steps back up to `gefs_cycle_retries` further 6h cycles on a real
"not yet available" signal, probing with a single lightweight request
(control member, `GEFS_TIMESTEP_HOURS` lead) before committing to fetch
every member/hour for that cycle.
"""

from __future__ import annotations

import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import httpx

from stage1a.config import Stage1ASettings, get_settings
from stage1a.forecast.provenance import ForecastPath, ForecastProvenance, RegionalForecastResult
from stage1a.gefs.errors import GEFSParseError, GEFSUnavailableError
from stage1a.gefs.parser import (
    GEFS_MEMBERS,
    GEFS_TIMESTEP_HOURS,
    build_regional_ensemble_forecast,
    decode_regional_mean_mm,
)
from stage1a.shared.contracts import BoundingBox

logger = logging.getLogger(__name__)

#: This system's officially-required forecast horizon (matches WN2 Mini's
#: own `FORECAST_HORIZON_HOURS`).
FORECAST_HORIZON_HOURS = 72

_CYCLE_HOURS = (0, 6, 12, 18)


def _candidate_cycles(forecast_start: datetime, lag_hours: float, retries: int) -> list[datetime]:
    """Real published-cycle candidates, most recent first.

    `forecast_start - lag_hours` is floored to the nearest real cycle
    boundary (never rounded up — a cycle from the future doesn't exist
    yet), then `retries` further cycles are offered 6h further back each,
    for the caller to try in order.
    """
    if forecast_start.tzinfo is None:
        forecast_start = forecast_start.replace(tzinfo=timezone.utc)
    adjusted = forecast_start.astimezone(timezone.utc) - timedelta(hours=lag_hours)
    floored_hour = max(h for h in _CYCLE_HOURS if h <= adjusted.hour)
    latest = adjusted.replace(hour=floored_hour, minute=0, second=0, microsecond=0)
    return [latest - timedelta(hours=6 * i) for i in range(retries + 1)]


def _gefs_file_url(base_url: str, cycle: datetime, member: str, lead_hour: int, bbox: BoundingBox) -> str:
    """The complete request URL, all query params in the string itself.

    REAL BUG FOUND AND FIXED THIS SESSION: an earlier version built the
    `file=`/`dir=`/`var_APCP=` params into the URL string and passed
    `leftlon`/`rightlon`/`toplat`/`bottomlat` separately via httpx's own
    `params=` kwarg. Confirmed live by inspecting `response.url`: httpx
    REPLACED the URL's existing query string with the separate `params`
    dict instead of merging them, silently dropping `file=`/`dir=`
    entirely -- NOMADS then returned a real HTTP 200 HTML error page
    ("Data Transfer: GFS Ensemble..."), which this module's error
    handling correctly treated as "unavailable," but for the wrong
    reason (a request bug, not a real publication-timing issue) --
    caused every real cycle to appear unavailable. Fixed by building one
    single query string with every parameter, never splitting them
    across the URL and a separate `params=` argument.
    """
    cycle_str = f"{cycle.hour:02d}"
    date_str = cycle.strftime("%Y%m%d")
    filename = f"ge{member}.t{cycle_str}z.pgrb2s.0p25.f{lead_hour:03d}"
    directory = f"/gefs.{date_str}/{cycle_str}/atmos/pgrb2sp25"
    return (
        f"{base_url}?file={filename}&var_APCP=on&lev_surface=on&subregion="
        f"&leftlon={bbox.min_lon}&rightlon={bbox.max_lon}"
        f"&toplat={bbox.max_lat}&bottomlat={bbox.min_lat}"
        f"&dir={directory}"
    )


#: A single flaky response shouldn't immediately abandon an entire cycle
#: -- real, transient NOMADS 302s/errors under load were observed live
#: this session, including on requests that had already succeeded moments
#: earlier for the identical URL. A few retries with backoff distinguishes
#: "genuinely not published" from a momentary failure under load.
_TRANSIENT_RETRY_ATTEMPTS = 4
_TRANSIENT_RETRY_DELAY_S = 2.0


def _fetch_one(
    client: httpx.Client,
    base_url: str,
    cycle: datetime,
    member: str,
    lead_hour: int,
    bbox: BoundingBox,
    timeout_s: float,
) -> bytes:
    """Fetch one (member, lead_hour) GRIB2 subset for `cycle`.

    Any response that isn't real GRIB2 bytes means this specific file
    isn't genuinely available -- confirmed live this session: a clean
    HTTP 403 "Request for Future Data" page for a not-yet-published
    cycle. Raises `GEFSUnavailableError` after retries are exhausted --
    "try the previous cycle," not a hard parse failure. A malformed body
    that DOES look GRIB-shaped is what `GEFSParseError` is for (see
    `parser.py`), not an HTML response.

    2026-08-20 fix (found via live testing, not inspection): a real
    network-level failure (timeout, connection drop, mid-response
    disconnect -- `httpx.RequestError` and its subclasses, e.g.
    `ReadTimeout`, `RemoteProtocolError`) is NOT an HTTP response at all,
    so the status-code check below never saw it -- it propagated
    uncaught, crashing the whole regional-forecast fetch instead of
    "try the previous cycle" like every other unavailability signal here.
    Confirmed reproducible against the real live transports (both S3 and
    NOMADS hit this independently in the same session). Now treated as
    just another transient-failure attempt, same retry/backoff as a bad
    status code -- matches `cwc/client.py`'s already-correct
    `except httpx.HTTPError` pattern, not independently invented.
    """
    url = _gefs_file_url(base_url, cycle, member, lead_hour, bbox)
    last_status = 0
    last_snippet = b""
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            response = client.get(url, timeout=timeout_s)
        except httpx.HTTPError as exc:
            last_status, last_snippet = -1, f"{type(exc).__name__}: {exc}".encode()[:80]
        else:
            if response.status_code < 400 and response.content[:4] == b"GRIB":
                return response.content
            last_status, last_snippet = response.status_code, response.content[:30]
        if attempt < _TRANSIENT_RETRY_ATTEMPTS - 1:
            time.sleep(_TRANSIENT_RETRY_DELAY_S * (2**attempt))  # exponential backoff

    raise GEFSUnavailableError(
        f"GEFS cycle {cycle.isoformat()} not available for {member} "
        f"f{lead_hour:03d} after {_TRANSIENT_RETRY_ATTEMPTS} attempts "
        f"(last: HTTP {last_status}, starting {last_snippet!r})."
    )


# --------------------------------------------------------------------------
# PRIMARY transport: NOAA Open Data Dissemination on S3 (no rate limiting)
# --------------------------------------------------------------------------

_APCP_IDX_MARKER = ":APCP:surface:"


def _s3_object_url(base_url: str, cycle: datetime, member: str, lead_hour: int) -> str:
    """The real S3 object URL for one member/lead-hour GRIB2 file.

    Path layout confirmed live this session against the real bucket:
        {base}/gefs.{YYYYMMDD}/{HH}/atmos/pgrb2sp25/ge{member}.t{HH}z.pgrb2s.0p25.f{HHH}
    """
    cycle_str = f"{cycle.hour:02d}"
    date_str = cycle.strftime("%Y%m%d")
    filename = f"ge{member}.t{cycle_str}z.pgrb2s.0p25.f{lead_hour:03d}"
    return f"{base_url}/gefs.{date_str}/{cycle_str}/atmos/pgrb2sp25/{filename}"


def _parse_apcp_byte_range(idx_text: str) -> tuple[int, Optional[int]]:
    """Byte range of the `APCP:surface` record, from a real `.idx` sidecar.

    Each `.idx` line is `record:startByte:date:VAR:level:...`; a record's
    end byte is the NEXT record's start minus one (the last record runs to
    end-of-file, hence `None`). Confirmed against a real sidecar this
    session -- e.g. `18:8492791:d=2026082006:APCP:surface:6-12 hour acc
    fcst:ENS=+1`, with record 19 starting at 8779783.

    Raises:
        GEFSParseError: if no APCP:surface record exists in the index --
            a real structural surprise, never guessed around.
    """
    starts: list[int] = []
    apcp_index: Optional[int] = None
    for line in idx_text.splitlines():
        parts = line.split(":")
        if len(parts) < 5:
            continue
        try:
            starts.append(int(parts[1]))
        except ValueError:
            continue
        if apcp_index is None and _APCP_IDX_MARKER in line:
            apcp_index = len(starts) - 1

    if apcp_index is None:
        raise GEFSParseError(
            f"No `{_APCP_IDX_MARKER}` record found in the GEFS .idx sidecar "
            f"({len(starts)} records parsed) -- refusing to guess a byte range."
        )
    start = starts[apcp_index]
    end = starts[apcp_index + 1] - 1 if apcp_index + 1 < len(starts) else None
    return start, end


def _fetch_one_s3(
    client: httpx.Client,
    base_url: str,
    cycle: datetime,
    member: str,
    lead_hour: int,
    timeout_s: float,
) -> bytes:
    """Fetch just the APCP record for one member/lead-hour, via HTTP Range.

    Two real requests: the small `.idx` sidecar (to locate the record),
    then a `Range:` request for only those bytes (~287KB) instead of the
    whole ~90MB global file. Confirmed live: the range request returns a
    real HTTP 206 with decodable GRIB2.

    Raises:
        GEFSUnavailableError: if the cycle/object isn't published (real
            S3 404), or a real network-level failure occurred (timeout,
            connection drop, mid-response disconnect -- see 2026-08-20
            fix note below) -- the caller treats either as "try an
            earlier cycle" or "fall through to NOMADS".
        GEFSParseError: if the object exists but its index or body is not
            the expected shape.

    2026-08-20 fix (found via live testing, not inspection): a real
    `httpx.RequestError` (e.g. `RemoteProtocolError`, `ReadTimeout`) from
    either `client.get()` call below is NOT an HTTP response, so the
    status-code checks never saw it -- it propagated uncaught, crashing
    the whole regional-forecast fetch instead of falling through to
    NOMADS like every other unavailability signal here. Confirmed
    reproducible against the real live S3 transport in this session. Now
    caught and converted to `GEFSUnavailableError`, matching
    `cwc/client.py`'s already-correct `except httpx.HTTPError` pattern.
    """
    object_url = _s3_object_url(base_url, cycle, member, lead_hour)

    try:
        idx_response = client.get(f"{object_url}.idx", timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise GEFSUnavailableError(
            f"GEFS S3 .idx fetch failed for {member} f{lead_hour:03d} "
            f"(network error: {type(exc).__name__}: {exc})."
        ) from exc
    if idx_response.status_code == 404:
        raise GEFSUnavailableError(
            f"GEFS cycle {cycle.isoformat()} not published on S3 for {member} "
            f"f{lead_hour:03d} (HTTP 404 on {object_url}.idx)."
        )
    if idx_response.status_code >= 400:
        raise GEFSUnavailableError(
            f"GEFS .idx fetch failed for {member} f{lead_hour:03d} "
            f"(HTTP {idx_response.status_code})."
        )

    start, end = _parse_apcp_byte_range(idx_response.text)
    range_header = f"bytes={start}-{end}" if end is not None else f"bytes={start}-"
    try:
        response = client.get(object_url, headers={"Range": range_header}, timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise GEFSUnavailableError(
            f"GEFS S3 range fetch failed for {member} f{lead_hour:03d} "
            f"(network error: {type(exc).__name__}: {exc})."
        ) from exc
    if response.status_code >= 400:
        raise GEFSUnavailableError(
            f"GEFS range fetch failed for {member} f{lead_hour:03d} "
            f"(HTTP {response.status_code})."
        )
    if response.content[:4] != b"GRIB":
        raise GEFSParseError(
            f"GEFS S3 range response for {member} f{lead_hour:03d} is not "
            f"GRIB2 (starts {response.content[:30]!r})."
        )
    return response.content


def _fetch_one_any_transport(
    client: httpx.Client,
    settings: Stage1ASettings,
    cycle: datetime,
    member: str,
    lead_hour: int,
    bbox: BoundingBox,
) -> bytes:
    """Fetch one member/lead-hour record, S3 first, NOMADS as fallback.

    S3 is primary because it has no rate limiting (NOMADS demonstrably
    load-sheds a real full-cycle fetch -- see the module docstring). The
    NOMADS filter path is kept as a genuine fallback: it is far more
    bandwidth-efficient (server-side subsetting), so it is worth using
    whenever S3 itself is unreachable.

    A `GEFSUnavailableError` from S3 falls through to NOMADS; only if
    BOTH transports report unavailable does it propagate. A
    `GEFSParseError` from either is a real structural bug and propagates
    immediately -- never silently retried on the other transport.
    """
    try:
        return _fetch_one_s3(
            client, settings.gefs_s3_base_url, cycle, member, lead_hour,
            settings.gefs_request_timeout_s,
        )
    except GEFSUnavailableError as s3_exc:
        logger.debug("S3 transport unavailable for %s f%03d (%s); trying NOMADS.", member, lead_hour, s3_exc)
        return _fetch_one(
            client, settings.gefs_filter_base_url, cycle, member, lead_hour, bbox,
            settings.gefs_request_timeout_s,
        )


def _probe_cycle(
    client: httpx.Client, settings: Stage1ASettings, cycle: datetime, bbox: BoundingBox
) -> bool:
    """True if `cycle` has real published data (probed with one small request)."""
    try:
        _fetch_one_any_transport(client, settings, cycle, "c00", GEFS_TIMESTEP_HOURS, bbox)
        return True
    except GEFSUnavailableError:
        return False


def fetch_gefs_forecast(
    bbox: BoundingBox,
    forecast_start: datetime,
    settings: Optional[Stage1ASettings] = None,
) -> RegionalForecastResult:
    """Fetch a real GEFS 0.25deg regional forecast (2026-08-20 amendment).

    Tries up to `settings.gefs_cycle_retries + 1` recent published cycles
    (most recent first), then fetches every real member/lead-hour pair for
    whichever cycle is actually available, with bounded concurrency.

    Raises:
        GEFSUnavailableError: if no cycle in the retry window is published
            yet (propagates to `forecast.fallback.get_regional_forecast`,
            which falls through to WeatherNext 2 Mini).
        GEFSParseError: if a cycle IS available but a response can't be
            decoded — a real bug, not something to fall through on (same
            convention as WN2ParseError).
    """
    settings = settings or get_settings()
    lead_hours = list(range(GEFS_TIMESTEP_HOURS, FORECAST_HORIZON_HOURS + 1, GEFS_TIMESTEP_HOURS))

    # follow_redirects=True: confirmed live this session -- NOMADS
    # sometimes responds with a real HTTP 302 (observed transiently,
    # presumably load-balancing across backend nodes) that resolves to
    # the real data on the next hop; httpx does not follow redirects by
    # default, and treating a 302 as "unavailable" without following it
    # caused every real, actually-published cycle to look unavailable.
    with httpx.Client(follow_redirects=True) as client:
        chosen_cycle: Optional[datetime] = None
        for cycle in _candidate_cycles(
            forecast_start, settings.gefs_publication_lag_hours, settings.gefs_cycle_retries
        ):
            if _probe_cycle(client, settings, cycle, bbox):
                chosen_cycle = cycle
                break
            logger.info("GEFS cycle %s not yet published; trying an earlier cycle.", cycle.isoformat())

        if chosen_cycle is None:
            raise GEFSUnavailableError(
                f"No published GEFS cycle found in the last "
                f"{settings.gefs_cycle_retries + 1} candidates before {forecast_start.isoformat()}. "
                "Falling through to WeatherNext 2 Mini."
            )

        jobs = [
            (member, hour)
            for member in GEFS_MEMBERS
            for hour in lead_hours
        ]
        values_by_member_hour: Dict[str, Dict[int, float]] = {m: {} for m in GEFS_MEMBERS}

        def _fetch_and_decode(member: str, hour: int) -> tuple[str, int, float]:
            content = _fetch_one_any_transport(
                client, settings, chosen_cycle, member, hour, bbox
            )
            with tempfile.NamedTemporaryFile(suffix=".grib2", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                value = decode_regional_mean_mm(tmp_path, bbox)
            finally:
                tmp_path.unlink(missing_ok=True)
            return member, hour, value

        with ThreadPoolExecutor(max_workers=settings.gefs_max_concurrent_requests) as pool:
            futures = [pool.submit(_fetch_and_decode, member, hour) for member, hour in jobs]
            for future in as_completed(futures):
                member, hour, value = future.result()  # a real exception here propagates, not swallowed
                values_by_member_hour[member][hour] = value

    forecast = build_regional_ensemble_forecast(values_by_member_hour, bbox, chosen_cycle)
    return RegionalForecastResult(
        forecast=forecast,
        provenance=ForecastProvenance(
            path=ForecastPath.GEFS,
            retrieved_at=datetime.now(timezone.utc),
            # Identifies the real CYCLE, not the transport: a single fetch
            # can legitimately mix transports (S3 primary, NOMADS fallback,
            # decided per record), so naming one here would be wrong for
            # any run that fell back partway through.
            source_file=f"gefs.{chosen_cycle.strftime('%Y%m%d')}/{chosen_cycle.hour:02d}z",
            synthetic=False,
        ),
    )
