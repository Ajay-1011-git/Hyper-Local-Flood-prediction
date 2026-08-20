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

## ADDENDUM — 2026-08-20: real GLB/anchor data arrived, T2.1-T2.4 amended

The real `vit_vellore_site.glb` and `anchor_point.json` (in
`blender_prep/output/`, gitignored, never committed) diverged from this
doc's original ground truth in confirmed ways. All changes below were
confirmed directly with the project owner, not inferred from any document.

1. **`Building_03` no longer exists.** The real 3D model replaced it with a
   garden, lawn, roads, and sidewalks. `REQUIRED_OBJECT_NAMES` is now
   `("Building_01", "Building_02", "Road_Network")`. Do not re-add
   `Building_03` without explicit re-confirmation.
2. **Garden/lawn physical treatment (confirmed with the project owner):**
   `Building_01`/`Building_02` remain impassable obstacles
   (`is_wall_node`). The circular garden bed in front of the MGR block
   (`Garden_Bed_Ring` in the real scene graph) is RAISED TERRAIN, not a
   wall — water only crosses it once flood depth exceeds its real raise
   height (measured from the real GLB: ~0.174m). Implemented as a pure
   elevation offset via `build_computational_mesh`'s new
   `raised_terrain_features` parameter, letting the solver's own slope
   physics handle "overtopping" — no special-cased wall logic. The lawn
   (`Garden_Lawn`/`KC_Lawn`) is passable and needs no special handling at
   all (plain terrain).
3. **Objects are fragmented, not one-piece-per-name.** The real export
   pipeline's simplify step splits each required object into several
   hash-suffixed scene nodes (`Building_01_1e1d4b`, etc. — 5 pieces for
   Building_01, 8 for Building_02, 4 for Road_Network). `glb_loader.py`
   now prefix-matches and merges all of an object's pieces (each piece's
   own world transform applied first) rather than requiring an exact name
   match.
4. **Coordinate convention is glTF Y-up, confirmed empirically** (a loaded
   node's world position was compared directly against the anchor file's
   own stated position and matched exactly) — ground plane is scene
   (X, Z), height is Y. All of T2.2/T2.3/T2.4 use (X, Z) for footprint/
   position and Y for height/elevation now.
5. **Georeferencing is no longer a single anchor + axis label.** The real
   `anchor_point.json` has 17 real GPS anchor points (`primary` +
   `additional_anchors`). Its own `scene_to_real_scale_factor` field does
   NOT mean "scene units to real meters" (confirmed by direct
   measurement — real GPS distance between two anchors matched their raw
   scene-space distance almost exactly, implying scale ≈ 1, not the
   stated ≈0.02) and is not used. `terrain/site_transform.py` instead
   computes its own Umeyama (1991) least-squares similarity fit (scale +
   rotation + translation) from all real anchor pairs — validated against
   the file's own reported fit accuracy (their RMS 8.202m vs. this fit's
   7.934m, with closely matching per-anchor residuals). `AnchorPoint`
   (the canonical single-point contract in `backend/shared/contracts.py`)
   is no longer populated or used internally by Stage 2 — superseded by
   `SiteTransform`. Real fit result on the actual site:
   `scale=0.9933, rms_residual_m=7.934, ref=(12.9691, 79.1563)`.
6. **T2.3's footprint ambiguity check was relaxed.** Every real building is
   genuinely 5-8 disconnected mesh pieces after simplify — this is now
   confirmed NORMAL (T2.1 already merges them before T2.3 sees them), not
   ambiguous geometry. `AmbiguousGeometryError` is now reserved for truly
   degenerate point sets (collinear/coincident vertices), not "more than
   one piece."
7. **Real VERIFY run against the actual GLB/anchor files** (not synthetic
   fixtures): `load_site_model` loads all 3 required objects with real
   geometry; `extract_building_footprints` gives Building_01
   height=23.31m/area=7452.3m², Building_02 height=27.16m/area=2331.7m²;
   `Garden_Bed_Ring`'s real footprint (area=288.1m², raise=0.174m) was
   located and fed into `build_computational_mesh` via
   `raised_terrain_features`, producing 7,458 nodes / 14,737 edges with
   2,447 wall nodes correctly split across the two real buildings and 67
   nodes correctly inside the garden's raised footprint. Elevation values
   in this specific run were NaN because no real Stage 1B DEM raster for
   this site was reachable in-session (a synthetic-fixture raster,
   geographically elsewhere, was used only to exercise the plumbing) —
   T2.2's own real-raster unit tests separately confirm the interpolation
   logic itself is correct; re-run this VERIFY against the real regional
   DEM once reachable.
8. `terrain/anchor_transform.py` (the old single-anchor/axis-label
   implementation) was deleted, fully superseded by `site_transform.py`.
   GenCast remains explicitly out of scope and must never be reintroduced
   as a fallback for anything in Stage 2, per standing instruction.

## ADDENDUM — 2026-08-20 (cont.): real DEM registered, T2.5 solver bug found on real mesh

9. **Real Stage 1B DEM fetched and registered** for the real site (with
   the user's explicit one-off permission to touch `backend/stage1b/`,
   normally out of scope — see `backend/stage1b/CLAUDE.md`'s own
   addendum for full detail). While doing this, found and fixed a real
   cross-stage bug: Stage 2's own DB integration test had been silently
   creating the shared `dem_metadata` table with an incomplete schema on
   a fresh Postgres (calling `create_all()` on its own read-only column
   subset before Stage 1B's real `init_models()` ever ran) — fixed the
   live table and the test (never creates a table it doesn't own now;
   skips cleanly if missing instead). T2.2's `find_terrain_grid_path` +
   `interpolate_terrain` now resolve and return REAL finite elevation
   (~118.3–119.3m at the site), not NaN.
10. **T2.5 (`solver/shallow_water_solver.py`) was already implemented**
    (built earlier this session, before this file's other addendum
    entries) — a real Bates/Horritt/Fewtrell (2010) local inertial
    solver, already tested against synthetic fixtures. Running it for
    the first time against the REAL 7,458-node/14,737-edge VIT Vellore
    mesh surfaced a real, genuine numerical bug the synthetic tests never
    exercised: the per-edge flux limiter only checked each edge's
    discharge against the smaller endpoint's available volume in
    isolation, so a node with several simultaneously-open edges (every
    real interior node has up to 4, vs. the synthetic tests' smaller/
    sparser fixtures) could have them each individually judged "safe"
    while jointly overdrawing the node in one sub-step — produced tiny
    negative depths (~-2e-4 m), correctly caught by
    `SolverInstabilityError` (never silently clamped). Fixed by summing
    each node's total real outflow across ALL its edges per sub-step and
    scaling every edge touching an over-committed node down
    proportionally. Re-verified against the real mesh: a 3-hour real
    rainfall trajectory (15/25/10 mm/hr) runs stably, mass conservation
    is exact (ratio 0.999999999999998), zero depth inside any wall node,
    and the raised `Garden_Bed_Ring` correctly shows small nonzero depth
    from direct rainfall (not overtopping in this particular light-rain
    trajectory — the mechanism is in place via the elevation offset, not
    separately tested here). 55/55 tests still pass, mypy clean.
11. **T2.6 (`gnn/model.py`+`training.py`+`graph_builder.py`) real-VERIFIED
    against the real mesh too**, same day: built the real 7,458-node
    graph, generated a real 6-hour solver trajectory (T2.5) as training
    data, trained the single-scale SWE-GNN from scratch for 5 epochs on
    Apple Silicon MPS. Unlike T2.5, this surfaced no bugs — training loss
    decreased monotonically every epoch (0.0794 → 0.0405), one-step
    validation MAE against the solver was small and finite
    (depth 0.0185m, velocity 0.0086 m/s), and `inject_boundary`'s
    ghost-cell-equivalent mechanism was confirmed to actually change the
    model's downstream prediction for the injected node on the real
    graph. No code changes were needed for T2.6.

## ADDENDUM — 2026-08-20 (cont.): T2.7 ensemble propagation, built and real-VERIFIED

12. **New: `gnn/ensemble.py`.** `run_ensemble(forecast, nodes, edges,
    model, cell_area_m2, hazard_threshold_m, validation_error_m,
    simulation_id, device=None) -> SimulationResult`. Two deliberate,
    explicitly-flagged design decisions (see the module's own docstring
    for full reasoning, since neither is directly confirmed against the
    real `RBTV1/mSWE-GNN` repo's own production inference code):
    - Production ensemble runs go through T2.6's GNN (autoregressive
      rollout, dry-start seed), not T2.5's solver — the solver remains
      the training-data generator / fallback, matching why
      `SimulationResult.validation_error_m` exists at all (it's the
      GNN's own MAE against the solver; would be meaningless if the
      solver produced results directly).
    - The vendored single-scale GNN has no rainfall input feature
      (confirmed: only elevation/area static + previous depth/velocity
      dynamic). Rainfall forcing is applied by adding each step's real
      recharge (`inflow_mm/1000`, matching T2.5's own uniform-recharge
      convention) directly into every non-wall node's most recent
      depth-history entry before the forward pass — the general form of
      `inject_boundary`'s single-node ghost-cell mechanism.
    - `hazard_threshold_m` and `validation_error_m` are REQUIRED
      parameters, never silently defaulted — the caller (eventually
      T2.9's route) must supply real, known values.
13. **Real VERIFY, against the actual VIT Vellore mesh** (7,458 nodes):
    trained the GNN on a real solver trajectory (real
    `validation_error_m` = 0.0185m, matching T2.6's earlier real number),
    then ran a real 5-member, 4-hour ensemble
    (`hazard_threshold_m=0.05`). Real output: 29,832 `NodeState`s
    (= 7,458 nodes × 4 hours, exact expected count), envelope
    `{max_depth_m: 0.097, hours_any_node_exceeds_threshold: 3,
    total_hours: 4, member_count: 5}`, every sampled `NodeState`'s
    `depth_min_m <= depth_mean_m <= depth_max_m` (and same for
    velocity) held, `ensemble_agreement_fraction` real and in [0, 1]
    (max observed 0.6). Ensemble wall-clock: ~41s for 5 members × 4
    hours on the full real mesh (MPS) — a real number for future
    performance planning, not claimed to be real-time yet at full
    50-150-member/72-hour scale. 59/59 tests pass (4 new ensemble tests
    added to `tests/test_gnn.py`, per the build doc's own file list),
    mypy clean.

## ADDENDUM — 2026-08-20 (cont.): T2.8 live sensor assimilation, built and real-VERIFIED

14. **New: `assimilation/ghost_cell_update.py` + `assimilation/errors.py`.**
    `assimilate_reading(reading, current_state, nodes, edges, target_x_m,
    target_y_m, sensor_mount_height_m, propagation_radius_m=20.0) ->
    SimulationResult`. Sensor not yet physically placed (confirmed with
    the project owner) — `target_x_m`/`target_y_m`/`sensor_mount_height_m`
    are required parameters, resolved by T2.9's route from new
    `Stage2Settings` fields (`sensor_target_x_m`/`_y_m`/
    `sensor_mount_height_m`, all `Optional[float] = None`), which raises
    `SensorLocationNotConfiguredError` until real values are set — the
    endpoint exists and is wired now, without a fabricated location.
15. **Method changed mid-task after a real numerical failure, kept for the
    record.** First attempt: re-run T2.5's solver for a short real-time
    window (~2s, the sensor's polling interval) seeded from the current
    state via a new `run_trajectory(..., initial_depth_by_node=...)`
    parameter. Real-tested against the actual mesh: produced physically
    absurd results (corrected depth drained to near-zero within 2
    simulated seconds, reported a >4 m/s velocity for an ordinary urban
    cell) — a sharp single-point correction against a gentle background is
    outside the regime T2.5's CFL/friction balance is tuned for (gently-
    varying sub-critical flow, per T2.5's own docstring). Reverted (the
    `initial_depth_by_node` solver parameter was removed again — unused,
    no reason to keep dead surface area). Replaced with DISTANCE-WEIGHTED
    NUDGING (successive correction / optimal interpolation — a real,
    standard, simpler data-assimilation technique): blend the observation
    with the model's background depth, weighted by real graph distance,
    linearly decaying to zero at `propagation_radius_m`. Well-behaved by
    construction (a convex combination of two non-negative depths can't
    go negative or spike) and satisfies "recomputing... locally" without
    touching the PDE solver's stability margins for a problem it wasn't
    designed for.
16. **Only depth is nudged.** The HC-SR04 measures distance to water
    surface, nothing else — `velocity_*_mps`/`rate_of_rise` are left as
    the model's own unaltered estimates at every node, including the
    target; nudging them would fabricate information the sensor never
    provided. `ensemble_agreement_fraction` IS re-derived at the exact
    target node (weight=1.0) since it's directly defined in terms of
    depth vs. `hazard_threshold_m` — a real recomputation, not a guess.
17. **Real VERIFY, against the actual 7,458-node VIT Vellore mesh**: used
    T2.7's real `SimulationResult` as `current_state`, picked a real
    non-wall node's real coordinates as the (still-unplaced) sensor
    target, injected `distance_cm=15.0` (mount height 0.5m → measured
    depth 0.35m). Real output: target node's depth_mean/min/max all
    collapse to exactly 0.35m, `ensemble_agreement_fraction=1.0`,
    velocity/rate_of_rise unchanged; immediate 2m-away neighbors land at
    0.318m, exactly matching the stated linear-decay formula
    (`0.9*0.35 + 0.1*0.0306`); a far node is confirmed untouched via
    Python object identity (`is`, not just equality); only 157/29,832
    `NodeState`s changed (confirms locality); wall-clock 0.128s (confirms
    "fast" — real number, not claimed). 68/68 tests pass (9 new, in
    `tests/test_assimilation.py`, per the build doc's file list), mypy
    clean.

## ADDENDUM — 2026-08-20 (cont.): T2.9 API routes, built and real-VERIFIED

18. **New: `routes.py`.** `GET /api/simulation/site/{site_id}` (TRD §5.1,
    returns the precomputed latest `SimulationResult`, 404 if none exists
    yet — never computes on demand, per TRD §4's own principle) and
    `POST /api/simulation/assimilate` (body: `SensorReading`; calls
    T2.8, broadcasts `sensor_assimilated` over its own `/ws/site/{site_id}`
    WebSocket). Runtime state (`nodes`/`edges`/latest `SimulationResult`
    per site) is a plain in-process dict, populated by a real
    `set_site_state()` — the actual T2.1-T2.7 precompute pipeline that
    fills it is Celery-orchestrated per TRD §4, out of this task's scope.
    `sensor_assimilated`'s payload shape (`{sensor_id, new_reading,
    updated_region}`) matches Stage 1B's own already-real, already-
    broadcasting implementation (`stage1b/sensor/ingest.py`, confirmed by
    reading its actual code) exactly — this endpoint is what finally
    makes `updated_region` real (Stage 1B's own version has always sent
    `None` there, honestly, since Stage 2 didn't exist yet).
19. **Real VERIFY: a real uvicorn server, seeded with the real pipeline's
    output, curl'd for real.** Ran the full real T2.1→T2.7 pipeline
    (real GLB, real DEM, real-trained GNN, real 4-member/3-hour ensemble)
    to seed `vit-vellore`'s site state, with `SENSOR_TARGET_X_M/Y_M`/
    `SENSOR_MOUNT_HEIGHT_M` set to a real non-wall node's coordinates for
    this VERIFY (the hardware itself still isn't placed). Started a real
    `uvicorn` process on `127.0.0.1:8765`. `curl GET
    /api/simulation/site/vit-vellore` → 200, real `simulation_id`,
    22,374 real `node_states`, real envelope
    (`{max_depth_m: 0.0255, hours_any_node_exceeds_threshold: 0,
    total_hours: 3, member_count: 4}`). `curl POST
    /api/simulation/assimilate` with a real `distance_cm=15.0` reading →
    200; the target node at the latest hour shows depth_mean/min/max all
    collapsed to exactly 0.35m (the real measured value),
    `ensemble_agreement_fraction=1.0`, velocity/rate_of_rise unchanged —
    a subsequent `curl GET` on the same site confirms the update
    persisted in the runtime state. 73/73 tests pass (5 new, in
    `tests/test_routes.py`, per the build doc's file list, including a
    real WebSocket test asserting the `sensor_assimilated` broadcast's
    exact payload shape), mypy clean.

## ADDENDUM — 2026-08-20 (cont.): T2.10 test suite completion, real coverage audit

20. **Coverage audit** (`pytest-cov`, added to `requirements.txt`,
    matching Stage 1B's own T1B.12 convention): 96% line coverage across
    all of `backend/stage2/` (1815 statements, 70 missed). Added one more
    real test (`test_post_assimilate_500_when_target_is_a_wall_node`) to
    close a real gap in `routes.py`'s own logic, raising it from 93% to
    96%. The remaining gaps, checked individually rather than chased for
    a round number:
    - `gnn/vendor/mswe_gnn/{gnn,models}.py` (91%/59%) — vendored
      third-party code; the uncovered lines are multiscale-only code
      paths (`MSGNN`, `intra_scale_gnn`) this project's single-scale
      `SWEGNN` usage structurally never reaches, not our logic to test.
    - `gnn/device.py` line 42 — the "MPS requested but unavailable,
      falling back to CPU" warning branch; only reachable on hardware
      without Metal support, not this development machine.
    - `routes.py` 121-122/124 — the dead-WebSocket-connection cleanup
      path inside `ConnectionManager.broadcast` (only reached when a
      `send_json` call itself raises, e.g. a client disconnecting
      mid-broadcast); a real but low-value path to force via a mock.
    - `solver/shallow_water_solver.py` line 253 — `SolverInstabilityError`'s
      own raise line; deliberately never triggered by a real test
      (that would mean an unstable run, which none of the real
      trajectories this project generates are) — the instability path
      itself IS exercised (see T2.5's real-mesh bug/fix earlier in this
      file), just not via a unit test that intentionally breaks the
      solver.
    - `terrain/site_transform.py` line 183 — the reflection-correction
      branch of the Umeyama SVD fit (`det(U)*det(Vt.T) < 0`); the real
      anchor data's own fit never hits this branch, and fabricating
      synthetic anchor points specifically to trigger a reflection would
      test the math library, not this project's logic.
    - `terrain/dem_source.py` lines 56/59, `config.py` line 70,
      `shared/contracts.py` line 53 — similar defensive/edge-case
      branches (URL-prefix fallthrough, comment-stripping edge case,
      import-guard) not exercised by any real call path in this project.
21. **Honest note on §E's acceptance checklist item 8** ("only
    `backend/stage2/` files were touched"): NOT literally true across
    this whole session — `backend/shared/contracts.py` was reconciled
    with Stage 3's independently-built version (explicit user decision,
    documented in `shared/contracts.py`'s own docstring), and
    `backend/stage1b/.env`/`backend/stage1b/CLAUDE.md` were touched
    once, with the user's explicit one-off permission, to register a
    real DEM for T2.2 (documented in `stage1b/CLAUDE.md`'s own
    addendum). Every other task's actual code changes were scoped to
    `backend/stage2/` only, per each task's own "Files you may touch."
22. **Full real VERIFY**: `pytest backend/stage2/tests/ -v` — 74/74
    passed (see this addendum's own commit for the complete real,
    unedited output). `mypy --config-file stage2/pyproject.toml stage2`
    — clean, 47 source files. T2.1 through T2.9 are all real-data-
    verified against the actual VIT Vellore site (not just synthetic
    fixtures) at least once each, per their own addenda above.
