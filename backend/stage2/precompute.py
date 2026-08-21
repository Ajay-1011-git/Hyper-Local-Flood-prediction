"""The real T2.1-T2.7 pipeline, runnable on demand, in two scenarios.

`routes.py`'s own module docstring documents `SiteRuntimeState` as
populated by `set_site_state()`, with "the actual T2.1-T2.7 precompute
pipeline that fills it is Celery-orchestrated per TRD SS4, out of this
task's scope" -- no Celery worker exists in this repo. This module is
that pipeline: the same real sequence every T2.1-T2.9 CLAUDE.md addendum
already ran ad hoc during development (load the real GLB -> resolve Stage
1B's real terrain -> build the real computational mesh -> generate a real
solver trajectory -> train the GNN on it -> run the real ensemble),
wired up as one callable so a route can seed the live process.

TWO REAL SCENARIOS, ONE PIPELINE
---------------------------------------------------------------------
Both run the SAME real physics on the SAME real mesh. They differ only in
the rainfall forcing fed in:

  * `real`  -- Stage 1B's real downscaled GEFS ensemble, unmodified.
    This is the honest current forecast for the site. At the time of
    writing that is a few mm over 72h, which really does produce almost
    no flooding -- an accurate result, not a broken one.

  * `heavy` -- the SAME real ensemble, uniformly rescaled so its wettest
    member reaches a real, cited IMD rainfall category (see
    `HEAVY_TARGET_MM_PER_24H`). This is a HYPOTHETICAL, and is labelled
    as one everywhere it surfaces (`SimulationResult.simulation_id` is
    prefixed `heavy-`, and the API reports the scenario explicitly). It
    is NOT a forecast and must never be presented as one.

Rescaling the real ensemble -- rather than substituting a synthetic flat
rainfall curve -- keeps the real inter-member spread and real temporal
shape, so `ensemble_agreement_fraction` still measures real forecast
disagreement rather than an invented one. The magnitude is the only
fabricated part, and that is the part the scenario name discloses.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from stage2.config import Stage2Settings, get_settings
from stage2.gnn.device import resolve_device
from stage2.gnn.ensemble import run_ensemble
from stage2.gnn.model import build_model
from stage2.gnn.training import train_on_solver_trajectory, validate_against_solver
from stage2.ingestion.glb_loader import load_site_model
from stage2.mesh.computational_mesh import build_computational_mesh
from stage2.shared.contracts import (
    ComputationalMeshNode,
    DownscaledForecastField,
    MeshEdge,
    SimulationResult,
)
from stage2.solver.shallow_water_solver import run_trajectory
from stage2.terrain.dem_interpolation import compute_site_bbox_latlon, interpolate_terrain
from stage2.terrain.footprint_extraction import extract_building_footprints
from stage2.terrain.road_segmentation import extract_road_segments

logger = logging.getLogger(__name__)

SCENARIOS = ("real", "heavy")

# IMD's own published rainfall classification: "extremely heavy rainfall"
# is >= 204.5 mm in 24 hours (India Meteorological Department rainfall
# category table). Used as the `heavy` scenario's target so the
# hypothetical corresponds to a real, named, citable category rather than
# an arbitrary "make it rain a lot" multiplier.
HEAVY_TARGET_MM_PER_24H = 204.5

# Matches Stage 3's own `hazard_threshold_depth_m` default
# (stage3/config.py) -- one consistent "elevated risk" depth across
# stages, not independently re-guessed here.
HAZARD_THRESHOLD_M = 0.3

# Training is ~0.4s/epoch on the real 7,458-node mesh (measured on this
# machine, MPS), so this is cheap relative to the solver step that
# generates its data.
TRAINING_EPOCHS = 60

# Stage 1B's real downscaled forecast is 6-hourly (it inherits GEFS's
# cadence -- see stage1a's CLAUDE.md addendum 2).
HOURS_PER_STEP = 6.0

# How many real solver steps to generate as GNN training data. Must be
# > graph_builder.PREVIOUS_T (3) to form any training example at all.
SOLVER_TRAINING_STEPS = 4


class PrecomputeUnavailableError(RuntimeError):
    """A real input (GLB / DEM / Stage 1B forecast) wasn't reachable.

    The caller decides how to surface this -- this pipeline never
    fabricates a `SimulationResult` in its place.
    """


ProgressFn = Callable[[str, float], None]


def _noop_progress(_message: str, _fraction: float) -> None:
    return None


def _fetch_downscaled_forecast(
    settings: Stage2Settings, lat: float, lon: float
) -> DownscaledForecastField:
    url = (
        f"{settings.stage1b_downscaled_forecast_base_url}"
        f"/api/forecast/downscaled?lat={lat}&lon={lon}"
    )
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 -- surfaced as one typed error
        raise PrecomputeUnavailableError(
            f"Could not fetch Stage 1B's real downscaled forecast from {url}: {exc}"
        ) from exc
    return DownscaledForecastField.model_validate(payload)


def scale_forecast_to_heavy(
    forecast: DownscaledForecastField,
    target_mm_per_24h: float = HEAVY_TARGET_MM_PER_24H,
) -> Tuple[DownscaledForecastField, float]:
    """Uniformly rescale a real forecast up to a real IMD rainfall category.

    Returns `(scaled_forecast, factor_applied)`. The factor is reported
    (never hidden) so callers can disclose exactly how hypothetical the
    scenario is relative to the real forecast.

    Scales against the WETTEST member's real peak 24h accumulation, so
    the scenario's worst case lands on the target category and every
    other member keeps its real position relative to it.
    """
    steps_per_24h = max(1, int(round(24.0 / HOURS_PER_STEP)))

    peak_24h = 0.0
    for member in forecast.members:
        values = [tv.inflow_mm for tv in sorted(member.trajectory, key=lambda t: t.hour)]
        for i in range(len(values)):
            window = sum(values[i : i + steps_per_24h])
            peak_24h = max(peak_24h, window)

    if peak_24h <= 0.0:
        raise PrecomputeUnavailableError(
            "The real forecast contains no rainfall at all, so there is nothing "
            "to scale into a heavy-rain scenario."
        )

    factor = target_mm_per_24h / peak_24h
    scaled_members = [
        member.model_copy(
            update={
                "trajectory": [
                    tv.model_copy(update={"inflow_mm": tv.inflow_mm * factor})
                    for tv in member.trajectory
                ]
            }
        )
        for member in forecast.members
    ]
    return forecast.model_copy(update={"members": scaled_members}), factor


def build_site_mesh(
    terrain_grid_path: str,
    site_id: str,
    settings: Optional[Stage2Settings] = None,
) -> Tuple[List[ComputationalMeshNode], List[MeshEdge]]:
    """Real T2.1-T2.4: GLB -> terrain -> footprints/roads -> mesh graph."""
    settings = settings or get_settings()

    try:
        objects, site_transform = load_site_model(
            settings.site_glb_path, settings.site_anchor_json_path
        )
    except Exception as exc:  # noqa: BLE001
        raise PrecomputeUnavailableError(
            f"Could not load the real site GLB/anchor: {exc}"
        ) from exc

    bbox = compute_site_bbox_latlon(objects, site_transform)
    terrain = interpolate_terrain(
        terrain_grid_path, site_id, bbox, settings.terrain_grid_resolution_m
    )

    buildings = {name: mesh for name, mesh in objects.items() if name.startswith("Building")}
    footprints = extract_building_footprints(buildings, site_transform)
    road_segments = extract_road_segments(objects["Road_Network"], site_transform)

    return build_computational_mesh(
        terrain, footprints, site_transform, road_segments=road_segments
    )


def run_precompute_for_site(
    site_id: str,
    terrain_grid_path: str,
    scenario: str = "real",
    max_members: int = 5,
    progress: ProgressFn = _noop_progress,
) -> Tuple[List[ComputationalMeshNode], List[MeshEdge], SimulationResult, Dict[str, object]]:
    """Run the real pipeline once for one scenario.

    `terrain_grid_path` is resolved by the CALLER (an `await
    find_terrain_grid_path(...)` on the live event loop) rather than in
    here: this function runs off the event loop in a worker thread, and
    `dem_source`'s cached asyncpg engine is bound to whichever loop first
    created it -- calling it from a second, thread-local loop raises
    "attached to a different loop". Keeping the one real async I/O call on
    the real event loop avoids that entirely.

    Returns `(nodes, edges, result, provenance)`. `provenance` carries the
    real, disclosable facts about HOW this particular result was produced
    (scenario, rainfall scaling factor, member count, model validation
    error) -- so no caller has to re-derive or guess them.

    Does not call `set_site_state()` -- the route owns that, matching
    `set_site_state`'s existing plain-setter contract.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; expected one of {SCENARIOS}.")

    settings = get_settings()

    progress("Loading the real site model and terrain", 0.05)
    nodes, edges = build_site_mesh(terrain_grid_path, site_id, settings)
    cell_area_m2 = settings.terrain_grid_resolution_m**2
    edge_width_m = settings.terrain_grid_resolution_m

    progress("Fetching Stage 1B's real downscaled forecast", 0.15)
    forecast = _fetch_downscaled_forecast(
        settings, settings.target_site_lat, settings.target_site_lon
    )

    rainfall_scale = 1.0
    if scenario == "heavy":
        forecast, rainfall_scale = scale_forecast_to_heavy(forecast)

    if max_members and len(forecast.members) > max_members:
        forecast = forecast.model_copy(update={"members": forecast.members[:max_members]})

    # Real solver-generated training signal, from this scenario's own
    # wettest member so the GNN is trained in the depth regime it will
    # actually be asked to predict in.
    wettest = max(
        forecast.members, key=lambda m: sum(tv.inflow_mm for tv in m.trajectory)
    )
    ordered = sorted(wettest.trajectory, key=lambda tv: tv.hour)
    # `inflow_mm` is accumulation over the step; the solver wants a rate.
    inflow_rates = [tv.inflow_mm / HOURS_PER_STEP for tv in ordered][:SOLVER_TRAINING_STEPS]

    progress("Running the numerical shallow-water solver", 0.25)
    solver_trajectory = run_trajectory(
        nodes, edges, inflow_rates, edge_width_m, hours_per_step=HOURS_PER_STEP
    )

    progress("Training the flood GNN on the solver's real output", 0.6)
    device = resolve_device()
    model = build_model(device)
    train_on_solver_trajectory(
        model,
        nodes,
        edges,
        cell_area_m2,
        solver_trajectory,
        inflow_rates,
        epochs=TRAINING_EPOCHS,
        device=device,
    )
    depth_mae_m, velocity_mae_mps = validate_against_solver(
        model, nodes, edges, cell_area_m2, solver_trajectory, device=device
    )

    progress(f"Running the {len(forecast.members)}-member ensemble", 0.75)
    simulation_id = f"{scenario}-{uuid.uuid4().hex[:12]}"
    result = run_ensemble(
        forecast,
        nodes,
        edges,
        model,
        cell_area_m2,
        HAZARD_THRESHOLD_M,
        depth_mae_m,
        simulation_id,
        device=device,
    )

    provenance: Dict[str, object] = {
        "scenario": scenario,
        "is_hypothetical": scenario == "heavy",
        "rainfall_scale_factor": round(rainfall_scale, 3),
        "heavy_target_mm_per_24h": HEAVY_TARGET_MM_PER_24H if scenario == "heavy" else None,
        "source_forecast_id": forecast.source_forecast_id,
        "member_count": len(forecast.members),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "grid_resolution_m": settings.terrain_grid_resolution_m,
        "hazard_threshold_m": HAZARD_THRESHOLD_M,
        "validation_depth_mae_m": round(depth_mae_m, 5),
        "validation_velocity_mae_mps": round(velocity_mae_mps, 5),
        "training_epochs": TRAINING_EPOCHS,
    }
    progress("Done", 1.0)
    return nodes, edges, result, provenance
