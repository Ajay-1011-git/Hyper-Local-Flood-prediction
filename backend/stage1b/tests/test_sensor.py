"""Tests for T1B.11 — sensor ingestion endpoint + WebSocket broadcast.

Runs a REAL uvicorn server as a subprocess (not an in-process ASGI
transport) and talks to it with real HTTP (`requests`) and a real
WebSocket client (`websockets`) — this sidesteps every event-loop-sharing
issue documented in T1B.1/T1B.9's tests (different OS process entirely,
no shared Python event loop to collide over), and is exactly the
technique used for this task's manual VERIFY run (see the commit
message) — these tests automate the same real behavior.
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
