"""Shared pytest fixtures for Stage 1B's test suite."""

from __future__ import annotations

import pytest

from backend.stage1b.tnwrd import client as tnwrd_client


@pytest.fixture(autouse=True)
def _clear_tnwrd_cache():
    """Reset `tnwrd/client.py`'s in-process telemetry cache around every test.

    That cache (added 2026-08-20 — the real fetch is ~24MB/17s, far from
    the "cheap" the old call site claimed) is deliberately module-level
    global state, which would otherwise leak between tests: a test that
    mocks `requests.get`/`pd.read_csv` would silently receive an earlier
    test's cached DataFrame and never exercise its own mocks at all.
    Caught for real by `test_fetch_deduplicates_across_resources` failing
    with `0 == 2` (zero downloads attempted) immediately after the cache
    was introduced — this fixture is the fix, not a precaution.
    """
    tnwrd_client._TELEMETRY_CACHE.clear()
    yield
    tnwrd_client._TELEMETRY_CACHE.clear()
