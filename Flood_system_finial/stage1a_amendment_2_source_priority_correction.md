# STAGE 1A — Amendment 2: Source Priority Correction (GEFS primary / WeatherNext 2 secondary / GenCast last-resort)

> **STATUS UPDATE (2026-08-20): the GEFS-primary / WN2-Mini-secondary part of this document is now BUILT AND LIVE-VERIFIED.** GEFS was a stub when this document was written; it is now a real client (`backend/stage1a/gefs/`) — 0.25° / ~27.75km, 31 real ensemble members, fetched live from NOAA (S3 Open Data primary, NOMADS GRIB-filter fallback) and confirmed winning the chain end-to-end. STEP 1's "if a GEFS client does not yet exist, build it" is therefore **done**; STEP 2's resolution/member-count flagging is recorded in `backend/stage1a/CLAUDE.md`'s Addendum 2, and STEP 3's doc propagation is complete (that same addendum, plus a dated Amendment 3 note in `flood_system_architecture.md` §2.1). The GenCast third tier remains **correctly refused** — see the superseding notice immediately below.

> **SUPERSEDED (2026-08-20) — the GenCast-as-tertiary-fallback decision below is incorrect and must not be built.** Confirmed directly with the project owner: GenCast has no available credentials, was removed outright (not deprioritised) in a prior session, and stays removed — including as a last-resort fallback. Do not restore `gencast/client.py`, `parser.py`, `devdata.py`, or wire `GenCastUnavailableError`/`load_precomputed_forecast` back into `get_regional_forecast()`. The GEFS-primary / WeatherNext-2-Mini-secondary part of this document is still correct and already reflects the live chain in `backend/stage1a/forecast/fallback.py` — only the third tier (GenCast) is wrong. If nothing is available from GEFS or WeatherNext 2 Mini, `get_regional_forecast()` raises `NoRegionalForecastAvailableError`; there is no third tier. See `backend/stage1a/CLAUDE.md`'s addendum for the authoritative current state.

> **This is a correction against both the original `stage1a_build_instructions.md` and the prior `Amendment 1` document (`stage1a_amendment_wn2_mini.md`).** Neither of those documents states the real, current decision correctly, and one of them contains an actual factual error that will cause you to build the wrong thing if followed literally. Do not proceed on assumption — follow the operating contract's WORKING METHOD (§A): audit first, report back, then act. Treat this document, not the two above it, as the current source of truth for regional-forecast source priority. Once you've made the changes below, you are also required to edit the older documents/canonical files so this doesn't have to be re-explained in a future session — see STEP 3.
>
> **Everything below this point is preserved as historical record and is superseded on the GenCast point per the notice above.**

---

## STEP 0 — Audit before touching anything

Before writing or changing any code:

1. Open `backend/stage1a/` and report, in plain terms: what currently exists for GenCast, for WeatherNext2 Mini (per Amendment 1), and for anything resembling a GEFS client. Be explicit if a GEFS client does not exist yet — do not assume it does because Amendment 1 mentions it.
2. Open `CLAUDE.md` (or wherever §A of the operating contract currently lives in this repo) and report its current content related to source priority / fallback order.
3. Report this audit before proceeding to STEP 1.

---

## What is actually true (confirmed by the project owner, not documented anywhere yet)

The real, current decision — made because GenCast's TPU compute requirement was not affordable for the team — is a **three-tier fallback chain**, in this exact priority order:

1. **GEFS (NOAA Global Ensemble Forecast System) — primary source.** Fully automated, no manual step, no TPU dependency. This is now the default path for `get_regional_forecast()`.
2. **WeatherNext 2 Cyclones Mini — secondary source.** Used only when GEFS is unavailable or fails ("struck"). This is the pipeline documented in Amendment 1 (`stage1a_amendment_wn2_mini.md`) — that document's mechanics (manual Colab-produced `.nc` file, `load_wn2_mini_forecast`, `parse_wn2_mini_output`, 8 members, 6-hourly steps, `resolution_km = 111.0`) are still correct and still apply. What Amendment 1 got wrong was treating this as a binary "GenCast replacement" and leaving primary/secondary order as an open question (its Open Question 1) — that question is now resolved: **WN2 Mini is secondary, not primary.**
3. **GenCast — tertiary / last-resort fallback only.** GenCast is *not* being removed from the architecture and is *not* being actively built out further beyond whatever already exists. It remains the final fallback in the chain, used only if both GEFS and WN2 Mini are unavailable. Do not deprioritize its existing typed-error/fallback-loader behavior (`GenCastUnavailableError`, `load_precomputed_forecast`) — that machinery stays, it just moves to last position in `get_regional_forecast()`'s try order instead of first.

### A factual error in Amendment 1 to correct now

Amendment 1's T1A.4 section says: *"Order of preference: (1) WN2 Mini file if present and valid, (2) GEFS via T1A.6/T1A.7 if built..."*

**This is wrong and must not be built as written.** T1A.6/T1A.7 are the **CWC / India-WRIS river-gauge client and nearest-station parser** — a hydrological cross-check on river/reservoir thresholds, an entirely different data source serving an entirely different purpose (per `flood_system_architecture.md` §"CWC" and the original `stage1a_build_instructions.md` T1A.6–T1A.7). GEFS is a **global weather ensemble forecast**, the same *kind* of source as GenCast and WeatherNext2 — it is not related to T1A.6/T1A.7 at all, and no GEFS client currently exists anywhere in the codebase or in any prior spec. If a GEFS client was, in fact, already built under some other task number during Stage 1A work, report that in the STEP 0 audit and reconcile against this description before proceeding. If it does not exist yet, it needs to be built as its own module (structured the same way T1A.2/T1A.3 or the WN2 Mini equivalents are — client + parser + typed unavailable-error), not conflated with the CWC pipeline.

---

## STEP 1 — Required code changes

- **Update `get_regional_forecast()`** so the try order is: GEFS → WeatherNext2 Mini → GenCast. Each tier logs which source was actually used via the existing `RegionalEnsembleForecast.source` field (already a free string per the shared contract — no schema change needed). Use honest source strings, e.g. `"GEFS"`, `"WeatherNext2_Cyclones_Mini"`, `"GenCast"`.
- **If a GEFS client does not yet exist:** build it as a new module (e.g. `backend/stage1a/gefs/client.py` + `backend/stage1a/gefs/parser.py`, following the same shape as T1A.2/T1A.3 — confirm GEFS's actual real access method and data format in-session before writing code against an assumed API, exactly as the operating contract requires for every other external source in this project). Raise a typed `GEFSUnavailableError` on failure, mirroring the pattern already used for `GenCastUnavailableError` and `WN2ForecastUnavailableError`. Do not reuse or modify the CWC (T1A.6/T1A.7) client for this.
- **If a GEFS client already exists under a different name/location:** do not duplicate it — wire the existing one into the corrected priority order and report the discrepancy between what exists and what Amendment 1 described.
- Leave the WeatherNext2 Mini and GenCast implementations' internal logic untouched — only their position in the fallback chain changes.

---

## STEP 2 — Do not guess, confirm if unresolved

1. Confirm GEFS's real access method (NOAA NOMADS, AWS Open Data bucket, or another route) by finding and citing actual current documentation in-session — do not assume an API shape.
2. Confirm whether GEFS's native resolution/member count/timestep spacing differs from GenCast's and WN2 Mini's enough to matter for `resolution_km` and downstream consumers (Stage 1B, Stage 2) — flag this explicitly in your task completion summary the same way Amendment 1 flagged WN2 Mini's 8-member/6-hourly difference. Do not silently absorb a mismatch.
3. If GEFS is unavailable in a given session (no network access to its data, or no time to build the client), fall back to WN2 Mini → GenCast per the same audit-first VERIFY discipline as the rest of this project — do not skip straight to fabricated data.

---

## STEP 3 — Propagate this correction into the canonical docs (required, not optional)

This project's own operating contract exists specifically to prevent a future session from drifting back to the wrong assumption because a doc wasn't updated. Since GEFS-primary/WN2-secondary/GenCast-last is currently **not written anywhere** in `flood_system_PRD.md`, `flood_system_TRD.md`, `flood_system_architecture.md`, or the original `stage1a_build_instructions.md` (all of which still describe GenCast alone as the regional-forecast source), a future Claude Code session reading only those files — without this document — will hallucinate back to the old order. To prevent that:

1. Edit `CLAUDE.md` (§A operating contract, as pasted into the repo) to add a short, explicit note under the Stage 1A section: current regional-forecast priority is GEFS → WeatherNext2 Mini → GenCast (last-resort only), with a one-line pointer to this file for the full rationale.
2. Add a short correction note at the top of `stage1a_build_instructions.md` and `stage1a_amendment_wn2_mini.md` (do not delete their original content — both still describe real, still-valid mechanics for their respective sources) stating that their stated fallback *order* is superseded by this document, with a link/reference to this file's filename.
3. Do **not** rewrite `flood_system_architecture.md` or the TRD/PRD to insert GEFS as if it had been in the original design — instead add a clearly dated amendment note (e.g. "Amendment 2, [date]: primary regional-forecast source changed from GenCast to GEFS due to TPU cost constraints; see `stage1a_amendment_2_source_priority_correction.md`") so the document's history stays honest rather than rewriting the past.

---

## VERIFY

- Paste the STEP 0 audit (current GenCast/WN2/GEFS code state, current `CLAUDE.md` content) before any other output.
- Run `get_regional_forecast()` three times, each time forcing a different tier to fail (GEFS down → falls to WN2; GEFS+WN2 down → falls to GenCast; all three down → typed error, not fabricated data), and paste the `source` field and outcome for each run.
- Paste the diffs (not full files) for every canonical doc edited in STEP 3, so the human can review exactly what was added versus what was left untouched.
- Confirm explicitly, in your completion summary, whether a GEFS client already existed before this session or was built fresh — this materially affects how much of STEP 1 was new work versus rewiring.
