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
