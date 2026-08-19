"""Sensor reading ingestion: validate, persist, broadcast — T1B.11.

## Request body: a real spec gap, reconciled

`flood_system_TRD.md` §5.1's `POST /api/sensor/reading` body is
`{ sensor_id, distance_cm, timestamp }` — no `site_id`, even though the
shared `SensorReading` contract (backend/shared/contracts.py) requires
one. This deployment has exactly one configured site
(`TARGET_SITE_ID`), so — same pattern already used and confirmed with the
human for T1B.9's route — `site_id` is resolved server-side to
`settings.target_site_id` rather than accepted from the client.

## WebSocket event: reconciled with the human (see this task's commit
message for the full back-and-forth)

TRD §5.2 names the broadcast event `sensor_assimilated`, payload
`{sensor_id, new_reading, updated_region}` — but frames it as firing
*after* Stage 2's assimilation job actually runs, which doesn't exist in
this repo (Stage 2 is a separate, not-yet-built stage). Broadcasting that
event as if real assimilation happened, when `SensorReading.assimilated`
is honestly still `False`, would misrepresent state to whoever
eventually builds Stage 2/3/4 against this event.

Confirmed with the human: use the TRD's exact event name and payload
shape, but keep the semantics honest — `new_reading.assimilated` stays
`False` (this stage genuinely didn't assimilate it into a simulation,
it only ingested and persisted it), and `updated_region` is `None`
(there's no simulation region to report on yet). The event means "a new
reading arrived for this site," not "Stage 2 processed it."
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import WebSocket
from pydantic import BaseModel

from backend.shared.contracts import SensorReading
from backend.stage1b.db import SensorReadingRow, get_db_session

logger = logging.getLogger(__name__)


class SensorReadingIngestRequest(BaseModel):
    """Request body per TRD §5.1 — no `site_id` (see module docstring)."""

    sensor_id: str
    distance_cm: float
    timestamp: datetime


class ConnectionManager:
    """Tracks active WebSocket subscribers per `site_id` and broadcasts to
    them. In-process only (a plain dict of connections) — correct for a
    single-worker deployment, which matches this project's demo scale;
    would need a shared backend (e.g. Redis pub/sub) to broadcast across
    multiple worker processes, flagged here rather than silently assumed
    to scale."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, site_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(site_id, set()).add(websocket)

    def disconnect(self, site_id: str, websocket: WebSocket) -> None:
        self._connections.get(site_id, set()).discard(websocket)

    async def broadcast(self, site_id: str, message: dict) -> int:
        """Sends `message` (JSON-serialized) to every subscriber of
        `site_id`. Returns how many subscribers received it (0 is not an
        error — nothing is listening yet, a real and common case for a
        WebSocket broadcast, not something to raise on)."""
        dead: list[WebSocket] = []
        sent = 0
        for ws in self._connections.get(site_id, set()):
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(site_id, ws)
        return sent


connection_manager = ConnectionManager()


async def ingest_sensor_reading(
    request: SensorReadingIngestRequest, site_id: str
) -> SensorReading:
    """Persist a sensor reading (idempotent on (sensor_id, timestamp), per
    T1B.1's unique constraint) and broadcast the TRD's `sensor_assimilated`
    event (honestly, per module docstring) to `/ws/site/{site_id}`
    subscribers. Returns the persisted reading as the shared contract
    type."""
    reading = SensorReading(
        sensor_id=request.sensor_id,
        site_id=site_id,
        distance_cm=request.distance_cm,
        timestamp=request.timestamp,
        assimilated=False,
    )

    async with get_db_session() as session:
        row = SensorReadingRow(
            sensor_id=reading.sensor_id,
            site_id=reading.site_id,
            distance_cm=reading.distance_cm,
            timestamp=reading.timestamp,
            assimilated=reading.assimilated,
        )
        session.add(row)
        try:
            await session.commit()
        except Exception:
            # Idempotency: a duplicate (sensor_id, timestamp) POST (e.g.
            # the ESP32 retrying after a dropped response) hits T1B.1's
            # unique constraint. Roll back and treat it as success —
            # broadcast still fires below, since a retried request should
            # still notify subscribers, not silently no-op.
            await session.rollback()

    sent_count = await connection_manager.broadcast(
        site_id,
        {
            "type": "sensor_assimilated",
            "payload": {
                "sensor_id": reading.sensor_id,
                "new_reading": reading.model_dump(mode="json"),
                "updated_region": None,  # no Stage 2 simulation exists yet
            },
        },
    )
    logger.info(
        "sensor reading %s@%s broadcast to %d subscriber(s) of site %s",
        reading.sensor_id,
        reading.timestamp,
        sent_count,
        site_id,
    )

    return reading
