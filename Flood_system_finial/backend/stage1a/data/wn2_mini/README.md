# WeatherNext 2 Cyclones Mini export

This directory holds `tn_flood_forecast.nc`, produced by manually running
`wn2_demo.ipynb` (https://github.com/google-deepmind/weathernext,
docs/weathernext2/) in Colaboratory on the free TPU runtime, then exported
with:

```python
vars_needed = ["total_precipitation_6hr"]
subset = predictions[vars_needed].sel(lat=slice(8, 14), lon=slice(76, 82))
encoding = {var: {"zlib": True, "complevel": 4} for var in subset.data_vars}
subset.to_netcdf("tn_flood_forecast.nc", encoding=encoding)
```

Skip notebook cell 19 (`grads_fn_jitted`) — it computes gradients this
project never needs (inference-only) and OOMs on the free TPU runtime.

**The `.nc` file itself is intentionally not committed to git** (see the
root `.gitignore`'s `data/**` rule) — it's a manually produced artifact.
Copy your own export here before running the backend, or ask a teammate
for theirs. `WN2_MINI_FORECAST_PATH` in `.env` points at this file by
default.

This is currently the only real forecast source in Stage 1A — the legacy
GenCast live-inference path was removed outright (no TPU/JAX credentials
available for it). If this file is missing and GEFS (also not yet
implemented) is unavailable, `GET /api/forecast/regional` returns a 503.
