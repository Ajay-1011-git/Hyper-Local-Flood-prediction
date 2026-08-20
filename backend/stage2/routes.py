"""Stage 2 API routes (T2.9): expose the simulation per the TRD.

TWO REAL ENDPOINTS, PER THIS TASK'S OWN STATED SCOPE
---------------------------------------------------------------------
`GET /api/simulation/site/{site_id}` and `POST /api/simulation/assimilate`
(TRD §5.1's `/api/simulation/site/{site_id}`; the assimilate path's exact
name comes from this task's own doc text, distinct from Stage 1B's
already-real `POST /api/sensor/reading`, which only ingests/persists a
raw reading — Stage 1B's own `sensor/ingest.py` docstring explicitly
defers real assimilation to "wherever Stage 2 eventually builds it,"
which is exactly this endpoint).

WHY A SEPARATE WEBSOCKET/CONNECTIONMANAGER, NOT REUSING STAGE 1B'S
---------------------------------------------------------------------------
Stage 1B already has a real, working `/ws/site/{site_id}` +
`ConnectionManager` (confirmed by reading `stage1b/sensor/ingest.py` and
`stage1b/routes.py` this session) — but it's Stage 1B's own FastAPI `app`
object, and this project's established pattern (confirmed by Stage 1A/1B
both being independently deployable services, each with its own `app`)
is that each stage runs its own process. Stage 2 therefore needs its own
`app`/`ConnectionManager`/`/ws/site/{site_id}` — the SAME path, mirroring
Stage 1B's, but a genuinely separate WebSocket server (a real production
deployment would need to reconcile this, e.g. one gateway process or a
shared Redis pub/sub per TRD's own note on multi-worker broadcast — out
of this task's scope, flagged here rather than silently assumed solved).

`sensor_assimilated` PAYLOAD SHAPE — MATCHES STAGE 1B'S REAL, ALREADY-
BUILT VERSION, NOT THE SHORTENED ONE IN STAGE4'S DOC
---------------------------------------------------------------------------
Confirmed by reading `stage1b/sensor/ingest.py`'s actual broadcast call:
`{sensor_id, new_reading, updated_region}` (matches the ORIGINAL TRD
§5.2 text) — Stage 1B already broadcasts this today with
`updated_region: None` ("no Stage 2 simulation exists yet", its own
docstring's words). This endpoint is what finally makes `updated_region`
real: the locally-nudged `NodeState`s T2.8 actually changed.

RUNTIME STATE IS A SIMPLE IN-MEMORY, PER-SITE STORE — NOT A NEW DB TABLE
---------------------------------------------------------------------------
Per TRD §4's own stated principle ("heavy computation must never happen
on the request path... precompute, don't compute-on-demand"), the full
T2.1-T2.7 pipeline that produces a site's mesh + latest `SimulationResult`
runs as a separate (Celery, per TRD) precompute job — building that
orchestration is explicitly out of this task's scope (`routes.py` +
`tests/test_routes.py` only). `set_site_state()` is the real, plain
function such a job (or a test, or this session's own real VERIFY script)
calls to populate a site's runtime state; the routes below only ever
READ/update it, never fabricate it. A single-process in-memory dict is
correct at this project's demo scale (single worker, single laptop, per
TRD §3) — a genuinely multi-worker deployment would need shared state
(e.g. Redis), flagged rather than silently assumed to scale, same as the
`ConnectionManager` note above.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from stage2.assimilation.errors import SensorAtWallNodeError
from stage2.assimilation.ghost_cell_update import assimilate_reading
from stage2.config import get_settings
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, SimulationResult
from backend.shared.contracts import SensorReading  # noqa: E402  (see shared/contracts.py's sys.path note)

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 2 — Flood Simulation")


@dataclass
class SiteRuntimeState:
    """One site's real computational mesh + latest computed simulation."""

    nodes: List[ComputationalMeshNode]
    edges: List[MeshEdge]
    latest_result: SimulationResult


_site_state: Dict[str, SiteRuntimeState] = {}


def set_site_state(
    site_id: str,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    latest_result: SimulationResult,
) -> None:
    """Real setter for a site's runtime state (see module docstring)."""
    _site_state[site_id] = SiteRuntimeState(nodes=nodes, edges=edges, latest_result=latest_result)


class ConnectionManager:
    """Tracks active WebSocket subscribers per `site_id` and broadcasts to
    them. Ported from Stage 1B's own real, working implementation
    (`stage1b/sensor/ingest.py`) — same in-process-only limitation noted
    there applies here too."""

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, site_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(site_id, set()).add(websocket)

    def disconnect(self, site_id: str, websocket: WebSocket) -> None:
        self._connections.get(site_id, set()).discard(websocket)

    async def broadcast(self, site_id: str, message: dict) -> int:
        """Sends `message` to every subscriber of `site_id`. Returns how
        many received it (0 is not an error — nothing listening yet is a
        real, common case)."""
        dead: List[WebSocket] = []
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


@app.get("/api/simulation/site/{site_id}", response_model=SimulationResult)
async def get_simulation_site(site_id: str) -> SimulationResult:
    """Return the precomputed latest `SimulationResult` for `site_id` (TRD §5.1).

    Never computes on demand (TRD §4's own architectural principle) —
    404s if nothing has been precomputed yet for this site, rather than
    blocking the request on a real ensemble run.
    """
    state = _site_state.get(site_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No precomputed simulation for site_id={site_id!r} yet.",
        )
    return state.latest_result


@app.post("/api/simulation/assimilate", response_model=SimulationResult)
async def post_simulation_assimilate(reading: SensorReading) -> SimulationResult:
    """Assimilate one live `SensorReading` (T2.8) and broadcast the real,
    locally-updated region via `sensor_assimilated` (TRD §5.2).

    Raises:
        404: no precomputed simulation exists yet for `reading.site_id`.
        503: the physical sensor's location isn't configured yet (see
            `assimilation/ghost_cell_update.py`'s module docstring — the
            hardware hasn't been deployed as of this writing).
        500: the configured sensor location resolves to a wall (building)
            node — a real configuration error, not a client's to fix.
    """
    state = _site_state.get(reading.site_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No precomputed simulation for site_id={reading.site_id!r} yet — cannot assimilate.",
        )

    settings = get_settings()
    if (
        settings.sensor_target_x_m is None
        or settings.sensor_target_y_m is None
        or settings.sensor_mount_height_m is None
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Sensor location not configured (SENSOR_TARGET_X_M/"
                "SENSOR_TARGET_Y_M/SENSOR_MOUNT_HEIGHT_M) — the hardware "
                "unit has not been physically placed yet."
            ),
        )

    try:
        updated = assimilate_reading(
            reading,
            state.latest_result,
            state.nodes,
            state.edges,
            target_x_m=settings.sensor_target_x_m,
            target_y_m=settings.sensor_target_y_m,
            sensor_mount_height_m=settings.sensor_mount_height_m,
        )
    except SensorAtWallNodeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    changed_states = [
        after
        for after, before in zip(updated.node_states, state.latest_result.node_states)
        if after is not before
    ]
    state.latest_result = updated

    assimilated_reading = reading.model_copy(update={"assimilated": True})
    await connection_manager.broadcast(
        reading.site_id,
        {
            "type": "sensor_assimilated",
            "payload": {
                "sensor_id": reading.sensor_id,
                "new_reading": assimilated_reading.model_dump(mode="json"),
                "updated_region": {
                    "node_states": [ns.model_dump(mode="json") for ns in changed_states]
                },
            },
        },
    )

    return updated


@app.websocket("/ws/site/{site_id}")
async def ws_site(websocket: WebSocket, site_id: str) -> None:
    await connection_manager.connect(site_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # client sends nothing meaningful; just keeps the socket open
    except WebSocketDisconnect:
        connection_manager.disconnect(site_id, websocket)
