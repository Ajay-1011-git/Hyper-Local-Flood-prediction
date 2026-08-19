"""GEFS (NOAA Global Ensemble Forecast System) integration — NOT implemented.

Reserved as the first link in `gencast.fallback.get_regional_forecast`'s
chain, per an explicit human decision (2026-08-19): WeatherNext 2 Mini
should stay secondary to GEFS once GEFS exists, because GEFS is a fully
automated source with no manual Colab step, while WN2 Mini requires a human
to run a notebook ahead of time.

GEFS integration itself was never in scope for this amendment — building it
was not requested. This module exists only so the chain's *shape* is right
now, and a real implementation can be dropped into `fetch_gefs_forecast`
later without touching `fallback.py` again.
"""
