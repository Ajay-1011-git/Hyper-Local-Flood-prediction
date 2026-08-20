# STAGE 2 — Complete Build Instructions (GLB-based, post-photogrammetry-pivot)
### Drift-proof, hallucination-resistant prompts aligned to the project's Architecture, TRD, and PRD documents

> **Context for this pivot.** Photogrammetry (Meshroom/COLMAP) did not produce a usable mesh. The team instead hand-built a Blender model of 3 VIT Vellore buildings and roads, which was processed separately (see `blender_mcp_build_instructions.md`) into a textured, correctly-scaled, georeferenced GLB with a known anchor point. **This changes Stage 2 materially: there is no terrain and no GPS-EXIF data in the source model** — both the georeferencing method and the terrain source are different from the original architecture's photogrammetry-based design. This document reflects that reality; it does not describe the photogrammetry pipeline anywhere.
>
> **Alignment guarantee.** Where this document doesn't explicitly override something, the original Architecture and TRD documents still apply — the physics model (mSWE-GNN), the contracts consumed from Stage 1B, and the output contracts to Stage 3 are unchanged.

---

# §A. Operating Contract

```md
# STAGE 2 — Claude Code Operating Contract (READ EVERY SESSION)

## What Stage 2 is
Stage 2 takes (a) a textured GLB model of the demo site (buildings + roads,
produced by a separate Blender MCP task, with an accompanying anchor-point
file), and (b) Stage 1B's DEM and DownscaledForecastField, and produces a
physics simulation of how the site floods — depth, velocity, rate-of-rise,
per node, per timestep, per ensemble member — using a fine-tuned mSWE-GNN
model, with a numerical solver as both training-data generator and fallback.

## GROUND TRUTH (never change without explicit human instruction)
- The source model has NO terrain and NO GPS metadata embedded — both must
  be constructed here, from Stage 1B's DEM and the human-supplied anchor
  point in `anchor_point.json`. Do not assume any terrain exists in the GLB.
- Building/road objects are named exactly `Building_01`, `Building_02`,
  `Building_03`, `Road_Network` per the Blender task's naming convention —
  match against these exact names, do not fuzzy-match or guess.
- Physics model is FIXED as `RBTV1/mSWE-GNN`, fine-tuned from pretrained
  weights if available, hybrid loss (solver-supervised + physics-residual).
  This is unchanged from the original architecture.
- Module boundaries: ALL code lives under `backend/stage2/`. Do not modify
  `backend/stage1a/`, `backend/stage1b/`, or Stage 3/4 code.
- Contracts consumed from Stage 1B (`DownscaledForecastField`,
  `SensorReading`) and produced for Stage 3 (`SimulationResult`, `NodeState`)
  are unchanged from the existing shared contract — do not modify them.

## ANTI-HALLUCINATION RULES
1. Never assume the DEM's native resolution is fine enough for the site
   without checking — Stage 1B's DEM is regional-scale (confirm its actual
   resolution from Stage 1B's output before assuming it's adequate for a
   ~50m-scale site; if it's coarse, the terrain will need interpolation,
   and that interpolation's limitation must be stated explicitly in output,
   not silently smoothed over).
2. Never fabricate a building's real-world height or footprint if the GLB's
   geometry is ambiguous (e.g., open-bottomed blocks) — inspect the actual
   mesh data and flag ambiguity rather than guessing a footprint shape.
3. Before using any geospatial/mesh library (`trimesh`, `pygltflib`,
   `rasterio`, `shapely`, etc.), confirm its current API in this session —
   do not assume function signatures from memory.
4. If the anchor point's north-orientation note (from `anchor_point.json`)
   is missing or ambiguous, STOP and ask — do not assume the GLB's default
   axes are geographically aligned.
5. Do not fabricate test results or VERIFY output. Paste real output.

## ANTI-DRIFT RULES
6. Only touch files listed in a task's "Files you may touch."
7. Do not modify the GLB itself — it's Blender MCP's finished deliverable.
   Stage 2 reads it, never edits or re-exports it.
8. Keep `SimulationResult`/`NodeState` byte-aligned with the existing
   contract (already defined in the Stage 2/3/4 combined document) — Stage 3
   depends on it unmodified.

## QUALITY GATES
- Python type hints everywhere; `mypy` passes.
- Every function taking DEM/mesh data validates shapes/CRS before computing.
- The interpolation/accuracy limitation of DEM-derived terrain (vs. what a
  real site survey would give) is documented in code comments and surfaced
  in the `SimulationResult`'s metadata, not hidden.
- Idempotent persistence; typed errors; no secrets in code.

## WORKING METHOD
Plan → wait for go on multi-file tasks → implement → run VERIFY, paste real
output → extend tests → commit `feat(T2.<n>): <summary>`.

## DEFINITION OF DONE
Code runs, `mypy` passes, VERIFY passes with real output, tests pass,
contracts unchanged, only permitted files touched.
```

---

# §B. Canonical Specifications

## B.1 Environment variables (`backend/stage2/.env.example`)

```
SITE_GLB_PATH=./blender_prep/output/vit_vellore_site.glb
SITE_ANCHOR_JSON_PATH=./blender_prep/output/anchor_point.json
DEM_SOURCE=stage1b   # pulled from Stage 1B's persisted DEM, not refetched here
MSWE_GNN_PRETRAINED_PATH=            # path to pretrained weights if found in RBTV1/mSWE-GNN repo
TERRAIN_GRID_RESOLUTION_M=1.0        # fine-grid spacing for the site terrain, in meters
DATABASE_URL=postgresql://localhost:5432/floodsystem
REDIS_URL=redis://localhost:6379/0
```

## B.2 Data contracts

**Consumed, unchanged, from Stage 1B** (`DownscaledForecastField`, `SensorReading` — copy verbatim from `stage1b_build_instructions.md` §B.2, do not redefine).

**New, specific to this GLB-based pivot** (`backend/stage2/shared/contracts.py`):

```python
from pydantic import BaseModel
from typing import List, Optional


class AnchorPoint(BaseModel):
    scene_object_name: str
    scene_local_position: List[float]      # [x, y, z] in Blender scene units
    real_world_lat: float
    real_world_lon: float
    real_world_elevation_m: Optional[float]
    scene_to_real_scale_factor: float
    north_axis: str                         # e.g. "+Y", confirmed from Blender task output


class BuildingFootprint(BaseModel):
    building_id: str            # "Building_01" etc.
    footprint_polygon: List[List[float]]   # [[x, y], ...] in real-world meters, site-local frame
    height_m: Optional[float]


class TerrainGrid(BaseModel):
    site_id: str
    resolution_m: float
    origin_lat: float
    origin_lon: float
    elevation_grid: List[List[float]]       # 2D array, meters
    interpolated_from_regional_dem: bool    # honesty flag — see Operating Contract rule 1


class ComputationalMeshNode(BaseModel):
    node_id: str
    x_m: float
    y_m: float
    elevation_m: float
    is_wall_node: bool
    building_id: Optional[str]   # set if is_wall_node is True
```

**Produced for Stage 3** (already defined in the earlier Stage 2/3/4 document — `NodeState`, `SimulationResult` — reuse verbatim, do not redefine here).

## B.3 File structure

```
backend/stage2/
├── CLAUDE.md
├── .env.example
├── shared/
│   └── contracts.py                # §B.2, plus imported NodeState/SimulationResult
├── ingestion/
│   ├── __init__.py
│   └── glb_loader.py                # T2.1
├── terrain/
│   ├── __init__.py
│   ├── dem_interpolation.py         # T2.2
│   └── footprint_extraction.py      # T2.3
├── mesh/
│   ├── __init__.py
│   └── computational_mesh.py        # T2.4
├── solver/
│   └── shallow_water_solver.py      # T2.5
├── gnn/
│   ├── model.py                      # T2.6 (fine-tuning + inference)
│   └── ensemble.py                   # T2.7
├── assimilation/
│   └── ghost_cell_update.py          # T2.8
├── routes.py                          # T2.9
├── db.py
├── config.py
└── tests/
```

---

# §C. Tasks

## T2.0 · Module scaffolding — [P0] · depends: none

> **PROMPT**
> Goal: skeleton in place.
> Files you may touch: everything under `backend/stage2/` (new).
> Requirements: create the structure in §B.3; `config.py` loading §B.1; paste §A into `CLAUDE.md`; paste §B.2 into `shared/contracts.py`, importing `DownscaledForecastField`/`SensorReading` from Stage 1B's module rather than redefining, and `NodeState`/`SimulationResult` from wherever they're currently defined (confirm the real import path — they were specified in an earlier combined Stage 2/3/4 document; locate the actual file before assuming its path); pin `requirements.txt` (trimesh or pygltflib for GLB reading, rasterio for DEM handling, torch, torch-geometric, numpy, scipy, fastapi, pydantic, pytest — verify each version on PyPI, do not guess).
> **VERIFY:** `pip install -r requirements.txt` clean; import check on both new and imported contracts; paste output.

## T2.1 · GLB ingestion — `backend/stage2/ingestion/glb_loader.py` · [P0] · depends: T2.0

> **PROMPT**
> Goal: load the Blender-produced GLB and anchor point, extract building and road geometry by name.
> Files you may touch: `backend/stage2/ingestion/glb_loader.py`, `backend/stage2/tests/test_ingestion.py`.
> Requirements: **verify the current API of whichever GLB-reading library you choose (trimesh or pygltflib) in this session before writing loading code — do not assume method names from memory.** Implement `load_site_model(glb_path: str, anchor_json_path: str) -> tuple[dict[str, mesh_data], AnchorPoint]`, returning a dict keyed by the exact object names (`Building_01`, `Building_02`, `Building_03`, `Road_Network`) mapped to their raw mesh geometry (vertices/faces), and the parsed `AnchorPoint`. If any expected object name is missing from the GLB, raise a typed `MissingSceneObjectError` naming exactly which object is missing — do not silently proceed with a partial building set.
> **VERIFY:** run against the real exported GLB; paste the vertex/face counts for each of the 4 expected objects and the full parsed `AnchorPoint`.

## T2.2 · DEM interpolation to site terrain — `backend/stage2/terrain/dem_interpolation.py` · [P0] · depends: T2.1

> **PROMPT**
> Goal: since the GLB has no terrain, build one from Stage 1B's DEM, positioned using the anchor point.
> Files you may touch: `backend/stage2/terrain/dem_interpolation.py`, `backend/stage2/tests/test_terrain.py`.
> Requirements: fetch Stage 1B's persisted DEM raster/grid (confirm the actual access method — direct file read of the GeoTIFF Stage 1B produced, or a DB/API call — check Stage 1B's actual implementation rather than assuming). Using the `AnchorPoint`'s real-world lat/lon and `scene_to_real_scale_factor`, compute the real-world bounding box the site's buildings occupy (from T2.1's mesh extents). Interpolate the (likely much coarser) regional DEM down to `TERRAIN_GRID_RESOLUTION_M` spacing across that bounding box, producing a `TerrainGrid`. **Set `interpolated_from_regional_dem = True` and document in a code comment that this is an approximation** — the project has no real fine-grained elevation survey of this specific site, since photogrammetry (which would have provided this) didn't work out. This is a real, stated limitation, not a bug to hide.
> **VERIFY:** paste the resulting `TerrainGrid`'s shape and elevation min/max/mean; confirm the bounding box used matches the buildings' real-world footprint (cross-check against T2.1's data via the anchor point).

## T2.3 · Building footprint extraction — `backend/stage2/terrain/footprint_extraction.py` · [P0] · depends: T2.1, T2.2

> **PROMPT**
> Goal: derive each building's 2D ground footprint for obstacle tagging.
> Files you may touch: `backend/stage2/terrain/footprint_extraction.py`, `backend/stage2/tests/test_terrain.py`.
> Requirements: for each building's mesh (`Building_01/02/03`), project its vertices onto the ground (XY) plane and compute the footprint polygon — verify the current API of whichever geometry library you use (e.g., `shapely`) for this projection/hull computation before writing code against it. Convert from scene-local coordinates to real-world meters using the anchor point and scale factor from T2.1. Also derive an approximate `height_m` from the mesh's Z-extent. Produce a `BuildingFootprint` per building. **If a building's mesh geometry is ambiguous (e.g., not a simple closed block, multiple disconnected pieces), flag this explicitly rather than guessing a single footprint** — ask the human if the geometry doesn't clearly resolve to one footprint per building.
> **VERIFY:** paste all 3 `BuildingFootprint` objects (polygon coordinates + height), and confirm the footprint areas are physically plausible for real campus buildings (not near-zero or absurdly large — sanity-check against the raw mesh bounding boxes from T2.1).

## T2.4 · Computational mesh assembly — `backend/stage2/mesh/computational_mesh.py` · [P0] · depends: T2.2, T2.3

> **PROMPT**
> Goal: combine the terrain grid and building footprints into the finite-volume graph the solver and GNN operate on.
> Files you may touch: `backend/stage2/mesh/computational_mesh.py`, `backend/stage2/tests/test_mesh.py`.
> Requirements: implement `build_computational_mesh(terrain: TerrainGrid, footprints: List[BuildingFootprint]) -> List[ComputationalMeshNode]`. For every terrain grid cell, create a `ComputationalMeshNode` with its position and elevation; for cells whose position falls inside any building's footprint polygon (a real point-in-polygon test, not an approximation), set `is_wall_node = True` and `building_id` to the matching building. Also derive graph edges (adjacency between neighboring grid cells) needed by the GNN — store these in whatever structure T2.6 will actually need (confirm against `RBTV1/mSWE-GNN`'s real expected input format before finalizing this function's output shape, rather than assuming a generic adjacency list is sufficient).
> **VERIFY:** paste the total node count, the count of wall nodes per building (sanity-check against each footprint's real area vs. grid resolution), and confirm no node is incorrectly double-tagged to two different buildings.

## T2.5 · Numerical shallow-water solver — `backend/stage2/solver/shallow_water_solver.py` · [P0] · depends: T2.4

> **PROMPT**
> Goal: a working 2D shallow-water (Saint-Venant) finite-volume solver over the computational mesh from T2.4, serving as both training-data generator and fallback.
> Files you may touch: `backend/stage2/solver/shallow_water_solver.py`, `backend/stage2/tests/test_solver.py`.
> Requirements: implement the solver honoring wall/obstacle nodes as no-flow boundaries. Provide a function to run N trajectories (50–150 per the original plan) varying inflow rate/intensity, given a boundary condition derived from a `DownscaledForecastField` member. This must run standalone as a genuine fallback capable of producing full `SimulationResult` output if the neural model isn't ready.
> **VERIFY:** run a single trajectory with a simple test inflow; paste depth/velocity at a handful of nodes over several timesteps, confirming water does not appear inside wall nodes and mass is approximately conserved (paste a total-volume-in vs. total-volume-in-mesh sanity check).

## T2.6 · mSWE-GNN fine-tuning and inference — `backend/stage2/gnn/model.py` · [P1] · depends: T2.5

> **PROMPT**
> Goal: fine-tune `RBTV1/mSWE-GNN` on this site's mesh and solver-generated data.
> Files you may touch: `backend/stage2/gnn/model.py`, `backend/stage2/tests/test_gnn.py`.
> Requirements: fork/clone `RBTV1/mSWE-GNN`; check whether it ships pretrained weights (if so, fine-tune from them rather than training from scratch, per the published low-data adaptation precedent). Adapt its input format to T2.4's computational mesh (confirm the real expected graph/tensor shape from the actual repo code, not assumed). Implement the hybrid loss (supervised against T2.5's solver output + physics-residual term via autograd). Wire the ghost-cell mechanism to accept boundary-condition updates from a `DownscaledForecastField` member and, separately, from a live `SensorReading` (T2.8 will call this).
> **VERIFY:** validate the fine-tuned model's output against the solver's output on held-out scenarios; paste the resulting error (depth/velocity MAE) — this becomes `SimulationResult.validation_error_m`.

## T2.7 · Ensemble propagation — `backend/stage2/gnn/ensemble.py` · [P0] · depends: T2.6

> **PROMPT**
> Goal: run every member of a `DownscaledForecastField` through the model, producing aggregated statistics only.
> Files you may touch: `backend/stage2/gnn/ensemble.py`, `backend/stage2/tests/test_gnn.py`.
> Requirements: implement `run_ensemble(forecast: DownscaledForecastField, mesh: List[ComputationalMeshNode]) -> SimulationResult`, computing per-node, per-timestep mean/min/max depth and velocity, and agreement fraction against a configurable hazard threshold. **Do not persist or return raw per-member arrays** — only the aggregated `NodeState` fields, per the project's data-volume/performance principle.
> **VERIFY:** run against a real `DownscaledForecastField` fixture (mock if Stage 1B's live endpoint isn't available yet); paste a sample `SimulationResult` confirming envelope (min/max) values bracket the mean sensibly.

## T2.8 · Live sensor assimilation — `backend/stage2/assimilation/ghost_cell_update.py` · [P0] · depends: T2.6

> **PROMPT**
> Goal: accept a live `SensorReading` and update the running simulation locally via ghost cells.
> Files you may touch: `backend/stage2/assimilation/ghost_cell_update.py`, `backend/stage2/tests/test_assimilation.py`.
> Requirements: implement `assimilate_reading(reading: SensorReading, current_state) -> updated_state`, injecting the reading at the nearest computational mesh node and recomputing only the locally affected region/timesteps — not a full re-run of T2.7.
> **VERIFY:** inject a test reading; paste before/after `NodeState` values at and near the affected node, confirming the update is local (nodes far from the sensor are unchanged) and fast (paste a real wall-clock timing).

## T2.9 · API routes — `backend/stage2/routes.py` · [P0] · depends: T2.7, T2.8

> **PROMPT**
> Goal: expose Stage 2 per the TRD.
> Files you may touch: `backend/stage2/routes.py`, `backend/stage2/tests/test_routes.py`.
> Requirements: implement `GET /api/simulation/site/{site_id}` (returns latest `SimulationResult`) and `POST /api/simulation/assimilate` (body: `SensorReading`, triggers T2.8, broadcasts via WebSocket), per the earlier Stage 2/3/4 document's endpoint definitions — confirm those exact shapes there before implementing, rather than re-deriving them independently.
> **VERIFY:** curl both; paste real responses.

## T2.10 · Test suite completion — [P0] · depends: all above

> **PROMPT**
> Goal: full passing coverage.
> Requirements: cover T2.1–T2.9's core logic; mock external dependencies (Stage 1B's live data) where the real endpoint isn't available.
> **VERIFY:** `pytest backend/stage2/tests/ -v`; paste full real output.

---

# §D. Build order

| Window | Tasks | Outcome |
|---|---|---|
| 1 | T2.0, T2.1 | GLB loading confirmed working against the real exported file |
| 2 | T2.2, T2.3 | Terrain generated, footprints extracted, both sanity-checked |
| 3 | T2.4 | Computational mesh assembled with correct wall-node tagging |
| 4 | T2.5 | Numerical solver working and validated (mass conservation check) |
| 5 | T2.6 | GNN fine-tuned, validated against solver |
| 6 | T2.7, T2.8 | Ensemble + live assimilation working |
| 7 | T2.9, T2.10 | API live, tests passing |

---

# §E. Final acceptance

1. The real GLB and anchor point load correctly, with all 4 named objects present. ✅
2. Terrain is generated from Stage 1B's real DEM, honestly flagged as interpolated/approximated, not fabricated as a real survey. ✅
3. Building footprints and wall-node tagging are correct and sanity-checked against real mesh geometry. ✅
4. The numerical solver conserves mass and respects wall nodes. ✅
5. The fine-tuned GNN's validation error against the solver is recorded and real. ✅
6. Ensemble output contains only aggregated statistics, never raw per-member data downstream. ✅
7. Live sensor assimilation is local and fast, confirmed by real timing. ✅
8. `pytest` and `mypy` pass cleanly; only `backend/stage2/` files were touched. ✅
