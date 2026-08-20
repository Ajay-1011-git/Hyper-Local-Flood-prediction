"""Shared test fixtures for the Stage 4 suite."""

from __future__ import annotations

import os
import socket

import pytest

#: Gate for tests that make REAL calls to Sarvam AI -- same convention as
#: Stage 1A's own `requires_live_host` (see that module's own comment for
#: the full reasoning: TRD §3.6 requires this system to run on a single
#: laptop with no hard live-internet dependency on demo day, so real
#: network tests are opt-out via SKIP_LIVE_NETWORK_TESTS, and skip
#: automatically -- not hard-fail -- when genuinely offline).
_LIVE_NETWORK_DISABLED = os.getenv("SKIP_LIVE_NETWORK_TESTS") == "1"


def _host_reachable(host: str, port: int = 443, timeout: float = 5.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def requires_live_host(host: str, port: int = 443) -> pytest.MarkDecorator:
    if _LIVE_NETWORK_DISABLED:
        return pytest.mark.skip(reason="SKIP_LIVE_NETWORK_TESTS=1 is set")
    return pytest.mark.skipif(
        not _host_reachable(host, port),
        reason=f"{host} not reachable from this environment",
    )
