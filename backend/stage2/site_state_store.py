"""Durable storage for a site's computed simulation state.

WHY THIS EXISTS — A REAL FAILURE, OBSERVED
---------------------------------------------------------------------
`routes.py` kept `_site_state` in a plain in-process dict, which its own
docstring correctly called "correct at this project's demo scale". That
turned out to be wrong in one specific, user-visible way: restarting the
Stage 2 process (a code reload, a crash, `run_all.sh` again) silently
discarded every computed simulation, and the dashboard went straight back
to "no live simulation for this site yet" with no explanation. Since a
real run costs 1-6 minutes of real physics, that is an expensive thing to
throw away by accident.

So results are mirrored into Redis — the same Redis instance Stage 3 and
Stage 4 already use (TRD SS3.6: one local instance shared across stages,
each owning its own keys). The in-process dict stays as the hot path;
Redis is consulted only on a miss.

WHAT IS PERSISTED, AND WHY ALL OF IT
---------------------------------------------------------------------
The mesh (`nodes`/`edges`) is stored alongside the `SimulationResult`,
not just the result. `POST /api/simulation/assimilate` needs the real
mesh to nudge the right neighbourhood (T2.8), so persisting only the
result would restore a site that renders correctly but silently cannot
accept a live sensor reading — a worse failure than the one being fixed,
because it looks fine.

Roughly 3 MB per site/scenario at this project's real mesh size (7,458
nodes / 14,737 edges), which is a normal Redis value size.

NEVER FAILS THE REQUEST
---------------------------------------------------------------------
Every operation degrades to the in-memory behaviour if Redis is down.
Persistence is an optimisation over recomputing; it is not a source of
truth this stage is entitled to fail over.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from stage2.config import get_settings
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, SimulationResult

logger = logging.getLogger(__name__)

_KEY = "stage2:site_state:{site_id}:{scenario}"

_client: Optional[aioredis.Redis] = None


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def save(
    site_id: str,
    scenario: str,
    nodes: List[ComputationalMeshNode],
    edges: List[MeshEdge],
    result: SimulationResult,
    provenance: Dict[str, object],
) -> bool:
    """Mirror one computed state into Redis. Returns whether it stuck."""
    payload = json.dumps(
        {
            "nodes": [n.model_dump(mode="json") for n in nodes],
            "edges": [e.model_dump(mode="json") for e in edges],
            "result": result.model_dump(mode="json"),
            "provenance": provenance,
        }
    )
    try:
        await get_client().set(_KEY.format(site_id=site_id, scenario=scenario), payload)
        return True
    except Exception as exc:  # noqa: BLE001 -- never fail the caller over a cache
        logger.warning("Could not persist site state for %s/%s: %s", site_id, scenario, exc)
        return False


async def load(
    site_id: str, scenario: str
) -> Optional[
    Tuple[List[ComputationalMeshNode], List[MeshEdge], SimulationResult, Dict[str, object]]
]:
    """Restore one previously-computed state, or `None` if there isn't one."""
    try:
        raw = await get_client().get(_KEY.format(site_id=site_id, scenario=scenario))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read site state for %s/%s: %s", site_id, scenario, exc)
        return None
    if raw is None:
        return None

    try:
        data = json.loads(raw)
        nodes = [ComputationalMeshNode.model_validate(n) for n in data["nodes"]]
        edges = [MeshEdge.model_validate(e) for e in data["edges"]]
        result = SimulationResult.model_validate(data["result"])
        provenance = data.get("provenance", {})
    except Exception as exc:  # noqa: BLE001
        # A stored value that no longer validates means the contract moved
        # under it. Recomputing is correct; serving a half-parsed
        # simulation would not be.
        logger.warning(
            "Stored site state for %s/%s is unreadable (%s); ignoring it.",
            site_id,
            scenario,
            exc,
        )
        return None

    return nodes, edges, result, provenance
