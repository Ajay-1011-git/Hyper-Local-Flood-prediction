"""Tests for Stage 2's API routes (T2.9).

Uses `starlette.testclient.TestClient` (sync, manages its own event
loop) — unlike Stage 1B's `routes.py`, this module has no module-level
cached async DB engine bound to a particular event loop (T2.9's
`_site_state` is a plain in-process dict, no asyncio primitives), so
none of T1B.9's test-file reasons to avoid `TestClient` apply here; it's
also the only client that supports `websocket_connect`, needed for the
WebSocket broadcast tests below.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import pytest
from starlette.testclient import TestClient

from stage2 import routes
from stage2.routes import app, set_site_state
from stage2.shared.contracts import ComputationalMeshNode, MeshEdge, NodeState, SimulationResult


def _grid_mesh(size: int = 5, resolution_m: float = 2.0) -> Tuple[List[ComputationalMeshNode], List[MeshEdge]]:
    nodes, edges = [], []
    grid = [[f"n_{r}_{c}" for c in range(size)] for r in range(size)]
    for r in range(size):
        for c in range(size):
            nodes.append(
                ComputationalMeshNode(
                    node_id=grid[r][c], x_m=c * resolution_m, y_m=r * resolution_m,
                    elevation_m=100.0, is_wall_node=False, building_id=None,
                )
            )
    for r in range(size):
        for c in range(size):
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if nr >= size or nc >= size:
                    continue
                edges.append(
                    MeshEdge(node_id_a=grid[r][c], node_id_b=grid[nr][nc], distance_m=resolution_m, slope=0.0)
                )
    return nodes, edges


def _simulation_result(site_id: str, nodes: List[ComputationalMeshNode], hour: int = 1) -> SimulationResult:
    node_states = [
        NodeState(
            node_id=n.node_id, hour=hour, depth_mean_m=0.02, depth_min_m=0.01, depth_max_m=0.03,
            velocity_mean_mps=0.05, velocity_min_mps=0.02, velocity_max_mps=0.08,
            rate_of_rise=0.01, ensemble_agreement_fraction=0.3, building_id=None,
        )
        for n in nodes
    ]
    return SimulationResult(
        simulation_id="sim-1", site_id=site_id, source_forecast_id="forecast-1",
        generated_at=datetime.now(timezone.utc), hazard_threshold_m=0.05,
        validation_error_m=0.02, node_states=node_states, envelope={"member_count": 3},
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_get_simulation_site_returns_seeded_result(client: TestClient) -> None:
    nodes, edges = _grid_mesh()
    result = _simulation_result("site-a", nodes)
    set_site_state("site-a", nodes, edges, result)

    resp = client.get("/api/simulation/site/site-a")

    assert resp.status_code == 200
    body = resp.json()
    assert body["simulation_id"] == "sim-1"
    assert body["site_id"] == "site-a"
    assert len(body["node_states"]) == len(nodes)


def test_get_simulation_site_404_when_not_seeded(client: TestClient) -> None:
    resp = client.get("/api/simulation/site/nonexistent-site")
    assert resp.status_code == 404


def test_post_assimilate_404_when_no_precomputed_simulation(client: TestClient) -> None:
    resp = client.post(
        "/api/simulation/assimilate",
        json={"sensor_id": "s1", "site_id": "nonexistent-site", "distance_cm": 20.0,
              "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    assert resp.status_code == 404


def test_post_assimilate_503_when_sensor_location_not_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    nodes, edges = _grid_mesh()
    result = _simulation_result("site-b", nodes)
    set_site_state("site-b", nodes, edges, result)

    class _UnconfiguredSettings:
        sensor_target_x_m = None
        sensor_target_y_m = None
        sensor_mount_height_m = None

    monkeypatch.setattr(routes, "get_settings", lambda: _UnconfiguredSettings())

    resp = client.post(
        "/api/simulation/assimilate",
        json={"sensor_id": "s1", "site_id": "site-b", "distance_cm": 20.0,
              "timestamp": datetime.now(timezone.utc).isoformat()},
    )
    assert resp.status_code == 503


def test_post_assimilate_success_updates_state_and_broadcasts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    nodes, edges = _grid_mesh(size=7)
    result = _simulation_result("site-c", nodes)
    set_site_state("site-c", nodes, edges, result)

    class _ConfiguredSettings:
        sensor_target_x_m = 6.0
        sensor_target_y_m = 6.0  # n_3_3, mesh center
        sensor_mount_height_m = 0.5

    monkeypatch.setattr(routes, "get_settings", lambda: _ConfiguredSettings())

    with client.websocket_connect("/ws/site/site-c") as ws:
        resp = client.post(
            "/api/simulation/assimilate",
            json={"sensor_id": "demo-1", "site_id": "site-c", "distance_cm": 30.0,
                  "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        assert resp.status_code == 200
        body = resp.json()
        target = next(ns for ns in body["node_states"] if ns["node_id"] == "n_3_3")
        assert target["depth_mean_m"] == pytest.approx(0.2)  # 0.5 - 0.30

        event = ws.receive_json()
        assert event["type"] == "sensor_assimilated"
        assert event["payload"]["sensor_id"] == "demo-1"
        assert event["payload"]["new_reading"]["assimilated"] is True
        changed_ids = {ns["node_id"] for ns in event["payload"]["updated_region"]["node_states"]}
        assert "n_3_3" in changed_ids

    # GET reflects the update afterward
    resp = client.get("/api/simulation/site/site-c")
    target_after = next(ns for ns in resp.json()["node_states"] if ns["node_id"] == "n_3_3")
    assert target_after["depth_mean_m"] == pytest.approx(0.2)
