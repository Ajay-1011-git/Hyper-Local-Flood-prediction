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
