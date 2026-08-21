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
READ/update it, never fabricate it.

UPDATE: the in-memory dict is now MIRRORED TO REDIS (`site_state_store`).
The original note here said a single-process dict was "correct at this
project's demo scale", which turned out to be wrong in one specific,
observed way: restarting this process silently discarded every computed
simulation, and the dashboard reverted to "no live simulation for this
site yet" — throwing away 1-6 minutes of real physics per scenario with
no indication why. Reads now go through `get_site_state()`, which
restores from Redis on a miss. A genuinely multi-worker deployment would
still need more than this (the `ConnectionManager` above is still
in-process only), which remains flagged rather than assumed solved.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from stage2.assimilation.errors import SensorAtWallNodeError
from stage2.assimilation.ghost_cell_update import assimilate_reading
from stage2.config import get_settings
from stage2 import site_state_store
from stage2.precompute import SCENARIOS, PrecomputeUnavailableError, run_precompute_for_site
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, SimulationResult
from backend.shared.contracts import SensorReading  # noqa: E402  (see shared/contracts.py's sys.path note)

logger = logging.getLogger(__name__)

app = FastAPI(title="Stage 2 — Flood Simulation")

# Real browser origins allowed to call this API -- an explicit allowlist,
# never "*" (same convention as Stage 4's routes.py). Closes the CORS gap
# flagged in Stage 4's own routes.py comment: the frontend calls this
# stage directly (frontend/src/api/client.ts and websocket.ts), not
# through Stage 4.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class SiteRuntimeState:
    """One site's real computational mesh + latest computed simulation."""

    nodes: List[ComputationalMeshNode]
    edges: List[MeshEdge]
    latest_result: SimulationResult
    #: Real, disclosable facts about how this result was produced
    #: (scenario, rainfall scaling, member count, model error) -- see
    #: `precompute.run_precompute_for_site`'s own return value. Empty for
    #: state seeded directly by `set_site_state` (e.g. tests).
    provenance: Dict[str, object] = field(default_factory=dict)


#: Keyed by `(site_id, scenario)`. The two scenarios are genuinely
#: different simulations of the same site (see precompute.py's docstring),
#: so they must not overwrite each other -- an operator comparing "what
#: the real forecast does" against "what extremely heavy rain would do"
#: needs both to still exist.
_site_state: Dict[Tuple[str, str], SiteRuntimeState] = {}


def set_site_state(
    site_id: str,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    latest_result: SimulationResult,
    scenario: str = "real",
    provenance: Optional[Dict[str, object]] = None,
) -> None:
    """Real setter for a site's runtime state (see module docstring).

    `scenario` defaults to `"real"` so every existing caller (and this
    module's own tests) keeps working unchanged.
    """
    _site_state[(site_id, scenario)] = SiteRuntimeState(
        nodes=nodes,
        edges=edges,
        latest_result=latest_result,
        provenance=provenance or {},
    )


async def get_site_state(site_id: str, scenario: str = "real") -> Optional[SiteRuntimeState]:
    """This site/scenario's state, restoring it from Redis on a miss.

    A restart empties `_site_state` but not Redis, so a previously-computed
    simulation survives (see `site_state_store`'s docstring for the real
    failure this fixes). The restored entry is put back in the in-process
    dict, so this only pays the deserialisation cost once.
    """
    state = _site_state.get((site_id, scenario))
    if state is not None:
        return state

    restored = await site_state_store.load(site_id, scenario)
    if restored is None:
        return None

    nodes, edges, result, provenance = restored
    logger.info("Restored persisted simulation for %s/%s", site_id, scenario)
    set_site_state(site_id, nodes, edges, result, scenario=scenario, provenance=provenance)
    return _site_state[(site_id, scenario)]


@dataclass
class PrecomputeJob:
    """Live status of one background precompute run."""

    state: str  # "running" | "done" | "failed"
    message: str
    progress: float
    detail: Optional[str] = None


#: Keyed the same way as `_site_state`. A job is kept after it finishes so
#: a client that polls late still learns the real outcome.
_precompute_jobs: Dict[Tuple[str, str], PrecomputeJob] = {}


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
async def get_simulation_site(site_id: str, scenario: str = "real") -> SimulationResult:
    """Return the precomputed latest `SimulationResult` for `site_id` (TRD §5.1).

    Never computes on demand (TRD §4's own architectural principle) —
    404s if nothing has been precomputed yet for this site, rather than
    blocking the request on a real ensemble run.
    """
    state = await get_site_state(site_id, scenario)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No precomputed {scenario!r} simulation for site_id={site_id!r} yet."
            ),
        )
    return state.latest_result


@app.get("/api/simulation/site/{site_id}/provenance")
async def get_simulation_provenance(site_id: str, scenario: str = "real") -> dict:
    """Real, disclosable facts about how a stored simulation was produced.

    Separate from the `SimulationResult` itself because that contract is
    shared verbatim with Stage 3/4 and must not gain Stage-2-private
    fields (this stage's own anti-drift rule 8).
    """
    state = await get_site_state(site_id, scenario)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No precomputed {scenario!r} simulation for site_id={site_id!r} yet.",
        )
    return dict(state.provenance)


async def _run_precompute_job(site_id: str, scenario: str, max_members: int) -> None:
    """Run one real precompute in the background and record its outcome."""
    from stage2.terrain.dem_source import Stage1BTerrainUnavailableError, find_terrain_grid_path

    key = (site_id, scenario)
    loop = asyncio.get_running_loop()

    def report(message: str, fraction: float) -> None:
        # Called from the worker thread -- hop back onto the loop's thread
        # before touching shared state the request handlers also read.
        loop.call_soon_threadsafe(
            _precompute_jobs.__setitem__,
            key,
            PrecomputeJob(state="running", message=message, progress=fraction),
        )

    settings = get_settings()
    try:
        # The one real async I/O call, awaited on the real event loop --
        # see precompute.py's own docstring for why it can't move into the
        # worker thread below.
        terrain_grid_path = await find_terrain_grid_path(
            settings.target_site_lat, settings.target_site_lon, settings
        )
        nodes, edges, result, provenance = await asyncio.to_thread(
            run_precompute_for_site, site_id, terrain_grid_path, scenario, max_members, report
        )
    except (PrecomputeUnavailableError, Stage1BTerrainUnavailableError) as exc:
        logger.warning("Precompute %s/%s failed: %s", site_id, scenario, exc)
        _precompute_jobs[key] = PrecomputeJob(
            state="failed", message="Precompute failed", progress=1.0, detail=str(exc)
        )
        return
    except Exception as exc:  # noqa: BLE001 -- a job must never die silently
        logger.exception("Precompute %s/%s crashed", site_id, scenario)
        _precompute_jobs[key] = PrecomputeJob(
            state="failed", message="Precompute crashed", progress=1.0, detail=str(exc)
        )
        return

    set_site_state(site_id, nodes, edges, result, scenario=scenario, provenance=provenance)
    # Mirror to Redis so this expensive result survives a restart.
    await site_state_store.save(site_id, scenario, nodes, edges, result, provenance)
    _precompute_jobs[key] = PrecomputeJob(
        state="done", message="Simulation ready", progress=1.0
    )
    # Real push so an open dashboard updates without polling the result
    # itself. Same event type the store already handles (T4B.1).
    await connection_manager.broadcast(
        site_id,
        {
            "type": "simulation_update",
            "payload": {
                "scenario": scenario,
                "simulation_id": result.simulation_id,
                "node_states": [],
                "envelope": result.envelope,
            },
        },
    )


@app.post("/api/simulation/precompute/{site_id}", status_code=202)
async def post_simulation_precompute(
    site_id: str, scenario: str = "real", max_members: int = 5
) -> dict:
    """Start the real T2.1-T2.7 pipeline for one scenario, in the background.

    Returns 202 immediately: a real run on the real 7,458-node mesh takes
    ~1-2 minutes (real measured figure -- the numerical solver that
    generates the GNN's training data dominates it), which no browser
    request should be held open for. Poll
    `GET /api/simulation/precompute/{site_id}/status` for real progress.

    Not a TRD SS4 violation of "never computes on demand": the real read
    path (`GET /api/simulation/site/{site_id}`) still only ever serves
    already-computed results. This is the trigger a Celery beat schedule
    would otherwise pull, exposed for a repo that has no worker yet.
    """
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario {scenario!r}; expected one of {list(SCENARIOS)}.",
        )

    key = (site_id, scenario)
    existing = _precompute_jobs.get(key)
    if existing is not None and existing.state == "running":
        # Idempotent: a second click while one is already running joins the
        # run in progress rather than starting a competing one.
        return {"state": existing.state, "message": existing.message, "progress": existing.progress}

    _precompute_jobs[key] = PrecomputeJob(
        state="running", message="Starting", progress=0.0
    )
    asyncio.create_task(_run_precompute_job(site_id, scenario, max_members))
    return {"state": "running", "message": "Starting", "progress": 0.0}


@app.get("/api/simulation/precompute/{site_id}/status")
async def get_simulation_precompute_status(site_id: str, scenario: str = "real") -> dict:
    """Real progress of a precompute run (see the POST above)."""
    job = _precompute_jobs.get((site_id, scenario))
    if job is None:
        # Checked through the accessor, so a result persisted before a
        # restart reports "done" rather than "never started".
        has_result = await get_site_state(site_id, scenario) is not None
        return {
            "state": "done" if has_result else "idle",
            "message": "Simulation ready" if has_result else "Not started",
            "progress": 1.0 if has_result else 0.0,
        }
    return {
        "state": job.state,
        "message": job.message,
        "progress": job.progress,
        "detail": job.detail,
    }


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
    # A live sensor reading is real-world observation, so it can only
    # correct the simulation of the real world -- never the hypothetical
    # heavy-rain scenario, which is not claiming to be happening.
    state = await get_site_state(reading.site_id, "real")
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


@app.get("/api/sensor/location/{site_id}")
async def get_sensor_location(site_id: str) -> dict:
    """Where the real ESP32/HC-SR04 unit is, if one has been placed.

    The hardware is not physically deployed yet (confirmed with the
    project owner; `SENSOR_TARGET_X_M`/`_Y_M`/`SENSOR_MOUNT_HEIGHT_M` are
    unset in `.env`), so this normally reports `configured: false` and the
    scene draws no marker. That is the honest state — a marker at a
    fabricated position would claim a deployment that hasn't happened.

    When the settings ARE filled in, this resolves the sensor to the
    NEAREST REAL MESH NODE and returns its `node_id`. The frontend already
    holds every node's real scene position (Stage 4's `/api/mesh-nodes`
    proxy), so returning an id rather than coordinates avoids
    re-implementing this project's scene-frame conversion a second time
    in TypeScript, and guarantees the marker sits exactly where the
    simulation's own data for that point lives.
    """
    settings = get_settings()
    x_m = settings.sensor_target_x_m
    y_m = settings.sensor_target_y_m
    mount_height_m = settings.sensor_mount_height_m

    if x_m is None or y_m is None or mount_height_m is None:
        return {
            "configured": False,
            "reason": (
                "No sensor hardware has been placed for this site yet "
                "(SENSOR_TARGET_X_M / SENSOR_TARGET_Y_M / SENSOR_MOUNT_HEIGHT_M unset)."
            ),
        }

    state = await get_site_state(site_id, "real")
    nearest_node_id = None
    if state is not None and state.nodes:
        nearest = min(
            state.nodes,
            key=lambda n: (n.x_m - x_m) ** 2 + (n.y_m - y_m) ** 2,
        )
        nearest_node_id = nearest.node_id

    return {
        "configured": True,
        "x_m": x_m,
        "y_m": y_m,
        "mount_height_m": mount_height_m,
        "nearest_node_id": nearest_node_id,
    }


@app.websocket("/ws/site/{site_id}")
async def ws_site(websocket: WebSocket, site_id: str) -> None:
    await connection_manager.connect(site_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # client sends nothing meaningful; just keeps the socket open
    except WebSocketDisconnect:
        connection_manager.disconnect(site_id, websocket)
