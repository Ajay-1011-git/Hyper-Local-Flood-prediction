# STAGE 1A — Amendment: Replace GenCast with WeatherNext 2 Cyclones Mini (verified, working pipeline)

> **This is a change request against the existing `stage1a_build_instructions.md`, not a fresh build.** A team member independently ran a real, working Colab session using WeatherNext 2's official demo notebook and confirmed a working end-to-end inference-to-file pipeline. This document tells you exactly what changed, what to audit first, and what to build now. Follow the operating contract's WORKING METHOD (§A) — plan first, audit before editing, don't overwrite work that's already correct.

---

## STEP 0 — Audit before touching anything

Before writing or changing any code:

1. Open `backend/stage1a/gencast/` (or wherever T1A.2–T1A.5 currently live) and summarize, in plain terms, exactly what exists: which functions are implemented, which are stubbed, what's tested, what's untested.
2. Report this summary back before proceeding. Do not assume the prior state matches the original `stage1a_build_instructions.md` exactly — audit the real code, not the spec.
3. Only after reporting the audit, proceed to the changes below.

---

## What actually changed (verified, not assumed)

A team member ran `wn2_demo.ipynb` (WeatherNext 2's official demo notebook, from `github.com/google-deepmind/weathernext`) directly in Colaboratory, using the free TPU runtime, and confirmed the following **by direct execution, not documentation**:

- **Model used:** `WeatherNextCyclones_Mini` — pretrained weights pulled from a public Google Cloud Storage (`gs://`) bucket referenced in the notebook. This is a different, newer checkpoint than "GenCast Mini" (which lives in a different notebook, `gencast_mini_demo.ipynb`, and is trained only through 2018) — do not conflate the two. WeatherNext 2 is trained on data through 2024.
- **Resolution:** 1.0° (~111km) — coarser than GenCast's native 0.25°, and coarser than GEFS's 0.25°.
- **Ensemble size:** 8 members (confirmed by direct inspection of the output array), not 50+.
- **Forecast horizon confirmed working:** 20 timesteps at 6-hour spacing = 120 hours, exceeding the 72-hour requirement.
- **Confirmed output field:** `total_precipitation_6hr` — the surface rainfall variable needed for this project, present and populated in the output dataset.
- **A real failure was hit and correctly resolved:** Cell 19 of the notebook (gradient/backward-pass computation, `grads_fn_jitted`) throws an OOM error, requiring >13GB — this cell computes gradients, which this project never needs (inference-only, no training, per the existing operating contract). **The fix is to skip this cell entirely, not to work around the OOM.** If you encounter this cell while re-running the notebook, do not attempt to make it fit in memory — it is not part of the required pipeline.
- **A real, working data-reduction pipeline was built and confirmed to reduce output from ~3.5GB to under 10MB:**
  ```python
  vars_needed = ["total_precipitation_6hr"]
  subset = predictions[vars_needed].sel(lat=slice(8, 14), lon=slice(76, 82))

  encoding = {var: {"zlib": True, "complevel": 4} for var in subset.data_vars}
  subset.to_netcdf("tn_flood_forecast.nc", encoding=encoding)
  ```
  The bounding box (`lat 8–14°N, lon 76–82°E`) covers Tamil Nadu. This is a confirmed-working snippet, not a proposal — use it as-is as the basis for the export step, adjusting only if the target site's actual coordinates require a different box (confirm against `TARGET_SITE_LAT`/`TARGET_SITE_LON` in `.env` before assuming this exact box is final).

---

## Required changes to T1A.2, T1A.3, T1A.4, T1A.5

### T1A.2 — reframed: "WeatherNext 2 Mini forecast ingestion," not "live inference client"

**Old requirement:** call GenCast inference in-process from the backend.
**New requirement:** the backend does **not** run inference itself. It loads an already-exported `.nc` file (produced by manually running `wn2_demo.ipynb` in Colab, per the confirmed pipeline above) from a known local path.

- Implement `load_wn2_mini_forecast(nc_file_path: str) -> xarray.Dataset` using `xarray.open_dataset`.
- Add `WN2_MINI_FORECAST_PATH` to `.env.example`, defaulting to a path like `./data/wn2_mini/tn_flood_forecast.nc`.
- If the file doesn't exist, raise a clearly typed `WN2ForecastUnavailableError` — do not fabricate data. This is now the trigger for falling back to GEFS (T1A.6, if already built) or the existing fallback path, not a live-inference failure.
- **Do not** attempt to reimplement the Colab inference pipeline as an automated backend job. That pipeline runs manually, ahead of time, exactly as it was proven to work. Automating TPU access from the backend is out of scope unless explicitly requested later.

### T1A.3 — parser updated for NetCDF input, 8 members, 6-hourly steps

**Old requirement:** parse GenCast's native JAX/xarray output structure (assumed, never confirmed).
**New requirement:** parse the confirmed real structure of the exported `.nc` file.

- Implement `parse_wn2_mini_output(ds: xarray.Dataset, bbox: BoundingBox) -> RegionalEnsembleForecast`.
- Map the dataset's `total_precipitation_6hr` variable, per ensemble member, per 6-hourly timestep, onto `EnsembleMember`/`TimestepValue`. `TimestepValue.hour` should hold the actual hour offset (0, 6, 12, …) — do not interpolate to hourly values; that decision belongs downstream if Stage 2 needs it, not here.
- Set `RegionalEnsembleForecast.source = "WeatherNext2_Cyclones_Mini"` (not `"GenCast"` — the contract's `source` field is a free string, update it to reflect the real source honestly).
- Set `RegionalEnsembleForecast.resolution_km = 111.0` (1.0° ≈ 111km) — do not leave the old `28.0` default in place, it's now inaccurate for this source.
- Validate that exactly 8 members are present; if not, raise a typed error rather than silently proceeding with a different count.
- **Flag explicitly in a code comment and in your task completion summary:** downstream consumers (Stage 1B's downscaling, Stage 2's simulation) need to know this source provides 8 members at 6-hour spacing, not 50 at hourly spacing — this is a real behavioral difference from what the original spec assumed, and it should not be silently absorbed.

### T1A.4 — fallback chain updated

- Order of preference: (1) WN2 Mini file if present and valid, (2) GEFS via T1A.6/T1A.7 if built, (3) the original precomputed-forecast fallback if neither is available. Implement `get_regional_forecast()` to try this chain in order, logging which source was actually used in the returned object (via the `source` field — already sufficient, no schema change needed).

### T1A.5 — Celery task simplified

- The task no longer triggers inference. It becomes: check for a new/updated `.nc` file at `WN2_MINI_FORECAST_PATH`, and if found and not yet ingested, parse and persist it. This can run on a simple schedule (e.g., check every few minutes) or be manually triggered — it is not a compute-heavy job anymore, so the Celery/async justification is weaker than before; keep it in Celery for consistency with the rest of the pipeline, but note in your completion summary that this task is now lightweight, not the same "protect the API from blocking on heavy compute" concern it originally addressed.

---

## Open questions — do not guess, ask if unresolved

1. **Should WeatherNext 2 Mini be the primary source or remain secondary to GEFS?** The default in this amendment treats it as secondary (GEFS is fully automated with no manual step; WN2 Mini requires a human to run Colab ahead of time). If the human wants it promoted to primary, the fallback order in T1A.4 needs to flip — confirm before assuming.
2. **Does Stage 2 need hourly boundary-condition updates, or can it work from 6-hourly input?** This affects whether an interpolation step is needed somewhere in the pipeline, and whose responsibility that is. Do not add interpolation speculatively — ask.
3. **How will the `.nc` file actually reach the backend before a demo?** Manual copy to a known local path (simplest, most aligned with the project's local-first reliability principle), or some sync mechanism (e.g., Google Drive)? This amendment assumes manual copy — confirm.

---

## VERIFY

- Run `load_wn2_mini_forecast()` and `parse_wn2_mini_output()` against the real `tn_flood_forecast.nc` file the team member already produced; paste the resulting `RegionalEnsembleForecast` as JSON, confirming 8 members, `resolution_km = 111.0`, `source = "WeatherNext2_Cyclones_Mini"`, and timestep hours at 6-hour spacing extending to at least 72.
- Confirm `get_regional_forecast()`'s fallback chain by temporarily removing the `.nc` file and confirming it falls through to the next available source without crashing.
- Paste the audit summary from Step 0 alongside the above, so the human can see what was already correct versus what was actually changed.
