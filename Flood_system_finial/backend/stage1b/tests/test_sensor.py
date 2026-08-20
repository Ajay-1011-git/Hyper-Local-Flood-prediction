"""Tests for T1B.11 — sensor ingestion endpoint + WebSocket broadcast.

The endpoint tests run a REAL uvicorn server as a subprocess (not an
in-process ASGI transport) and talk to it with real HTTP (`requests`) and
a real WebSocket client (`websockets`) — this sidesteps every
event-loop-sharing issue documented in T1B.1/T1B.9's tests (different OS
process entirely, no shared Python event loop to collide over), and is
exactly the technique used for this task's manual VERIFY run (see the
commit message) — these tests automate the same real behavior.

COVERAGE NOTE (from T1B.12's audit): because that server runs in a
subprocess, `coverage` cannot instrument it, so `sensor/ingest.py`
reports artificially low coverage even though these tests genuinely
exercise it end-to-end. That's a measurement artifact, NOT untested
code — verified by the tests below actually asserting real HTTP status
codes, real DB rows, and real WebSocket frames. The `ConnectionManager`
unit tests at the bottom of this file are separate: they cover edge
cases (dead-connection cleanup, broadcast with zero subscribers) that
the end-to-end tests genuinely don't reach, in-process where they're
directly assertable.

No external network is involved anywhere in this file — the sensor
ingestion path touches only the local DB and in-process WebSocket
subscribers (confirmed by reading routes.post_sensor_reading), so
T1B.12's "mock all external network calls" requirement has nothing to
mock here.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
import pytest
import requests
import websockets

from backend.stage1b.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PORT = 8099
_BASE_URL = f"http://127.0.0.1:{_PORT}"


def _sync_db_url() -> str:
    # config.settings.database_url is the plain postgresql:// form (T1B.1
    # normalizes to +asyncpg only inside db.py's async engine); psycopg2
    # needs the plain form directly.
    return settings.database_url


def _wait_for_server(timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            requests.get(f"{_BASE_URL}/docs", timeout=1)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.3)
    raise RuntimeError(f"uvicorn server never became ready: {last_error}")


@pytest.fixture(scope="module")
def live_server():
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.stage1b.routes:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(_PORT),
        ],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server()
        yield _BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(autouse=True)
def _cleanup_sensor_rows():
    yield
    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sensor_reading WHERE sensor_id LIKE 'test-sensor-%'"
            )
        conn.commit()
    finally:
        conn.close()


def test_post_sensor_reading_valid_token_returns_200(live_server):
    resp = requests.post(
        f"{live_server}/api/sensor/reading",
        json={
            "sensor_id": "test-sensor-001",
            "distance_cm": 42.5,
            "timestamp": "2026-08-19T10:00:00Z",
        },
        headers={"X-Sensor-Token": settings.sensor_ingest_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sensor_id"] == "test-sensor-001"
    assert body["site_id"] == settings.target_site_id
    assert body["assimilated"] is False


def test_post_sensor_reading_persists_to_db(live_server):
    requests.post(
        f"{live_server}/api/sensor/reading",
        json={
            "sensor_id": "test-sensor-002",
            "distance_cm": 15.0,
            "timestamp": "2026-08-19T10:05:00Z",
        },
        headers={"X-Sensor-Token": settings.sensor_ingest_token},
    )
    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sensor_id, distance_cm, assimilated FROM sensor_reading "
                "WHERE sensor_id = %s",
                ("test-sensor-002",),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "test-sensor-002"
    assert float(row[1]) == 15.0
    assert row[2] is False


def test_post_sensor_reading_invalid_token_returns_401(live_server):
    resp = requests.post(
        f"{live_server}/api/sensor/reading",
        json={
            "sensor_id": "test-sensor-003",
            "distance_cm": 1.0,
            "timestamp": "2026-08-19T10:10:00Z",
        },
        headers={"X-Sensor-Token": "wrong-token"},
    )
    assert resp.status_code == 401


def test_post_sensor_reading_missing_token_returns_401(live_server):
    resp = requests.post(
        f"{live_server}/api/sensor/reading",
        json={
            "sensor_id": "test-sensor-004",
            "distance_cm": 1.0,
            "timestamp": "2026-08-19T10:15:00Z",
        },
    )
    assert resp.status_code == 401


def test_post_sensor_reading_duplicate_is_idempotent(live_server):
    body = {
        "sensor_id": "test-sensor-005",
        "distance_cm": 7.0,
        "timestamp": "2026-08-19T10:20:00Z",
    }
    headers = {"X-Sensor-Token": settings.sensor_ingest_token}
    r1 = requests.post(f"{live_server}/api/sensor/reading", json=body, headers=headers)
    r2 = requests.post(f"{live_server}/api/sensor/reading", json=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM sensor_reading WHERE sensor_id = %s",
                ("test-sensor-005",),
            )
            count = cur.fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_websocket_receives_sensor_assimilated_broadcast(live_server):
    async def run():
        site_id = settings.target_site_id
        ws_url = live_server.replace("http://", "ws://") + f"/ws/site/{site_id}"
        async with websockets.connect(ws_url) as ws:
            await asyncio.sleep(0.3)  # let the subscription register server-side

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: requests.post(
                    f"{live_server}/api/sensor/reading",
                    json={
                        "sensor_id": "test-sensor-006",
                        "distance_cm": 33.3,
                        "timestamp": "2026-08-19T10:25:00Z",
                    },
                    headers={"X-Sensor-Token": settings.sensor_ingest_token},
                ),
            )

            message = await asyncio.wait_for(ws.recv(), timeout=10)
            return message

    import json

    raw = asyncio.run(run())
    message = json.loads(raw)
    assert message["type"] == "sensor_assimilated"
    assert message["payload"]["sensor_id"] == "test-sensor-006"
    assert message["payload"]["new_reading"]["assimilated"] is False
    assert message["payload"]["updated_region"] is None


# ---------------------------------------------------------------------------
# ConnectionManager unit tests (in-process — these cover edge cases the
# subprocess end-to-end tests above genuinely never reach, not just the
# same paths again)
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Minimal stand-in for starlette's WebSocket: records what was sent,
    and can be made to raise on send to simulate a dropped client."""

    def __init__(self, fail_on_send: bool = False):
        self.sent: list[dict] = []
        self.fail_on_send = fail_on_send
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message: dict):
        if self.fail_on_send:
            raise ConnectionResetError("simulated dropped client")
        self.sent.append(message)


def test_connection_manager_broadcasts_to_subscribers_of_that_site_only():
    from backend.stage1b.sensor.ingest import ConnectionManager

    async def run():
        manager = ConnectionManager()
        subscriber = _FakeWebSocket()
        other_site_subscriber = _FakeWebSocket()
        await manager.connect("site-a", subscriber)
        await manager.connect("site-b", other_site_subscriber)

        sent_count = await manager.broadcast("site-a", {"type": "x"})
        return sent_count, subscriber, other_site_subscriber

    sent_count, subscriber, other = asyncio.run(run())
    assert sent_count == 1
    assert subscriber.sent == [{"type": "x"}]
    assert other.sent == []  # site isolation: not leaked across sites


def test_connection_manager_broadcast_with_no_subscribers_is_not_an_error():
    from backend.stage1b.sensor.ingest import ConnectionManager

    async def run():
        manager = ConnectionManager()
        return await manager.broadcast("nobody-listening", {"type": "x"})

    # 0 is a real, common outcome (nothing subscribed yet), not a failure.
    assert asyncio.run(run()) == 0


def test_connection_manager_drops_dead_connections_on_broadcast():
    from backend.stage1b.sensor.ingest import ConnectionManager

    async def run():
        manager = ConnectionManager()
        healthy = _FakeWebSocket()
        dead = _FakeWebSocket(fail_on_send=True)
        await manager.connect("site-a", healthy)
        await manager.connect("site-a", dead)

        first = await manager.broadcast("site-a", {"type": "first"})
        # The dead one should have been evicted, so a second broadcast
        # doesn't keep retrying it.
        second = await manager.broadcast("site-a", {"type": "second"})
        return first, second, healthy

    first, second, healthy = asyncio.run(run())
    assert first == 1  # only the healthy one received it
    assert second == 1
    assert healthy.sent == [{"type": "first"}, {"type": "second"}]


def test_connection_manager_disconnect_removes_subscriber():
    from backend.stage1b.sensor.ingest import ConnectionManager

    async def run():
        manager = ConnectionManager()
        ws = _FakeWebSocket()
        await manager.connect("site-a", ws)
        manager.disconnect("site-a", ws)
        return await manager.broadcast("site-a", {"type": "x"})

    assert asyncio.run(run()) == 0


def test_connection_manager_disconnect_unknown_socket_is_safe():
    """A disconnect for a site/socket that was never registered must not
    raise (real case: a connection that failed during accept)."""
    from backend.stage1b.sensor.ingest import ConnectionManager

    manager = ConnectionManager()
    manager.disconnect("never-seen", _FakeWebSocket())  # must not raise
