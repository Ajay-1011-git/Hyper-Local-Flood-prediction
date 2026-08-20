"""GEFS (NOAA Global Ensemble Forecast System, 0.25deg) — REAL, PRIMARY source.

Built for real on 2026-08-20 at the project owner's request (previously an
honest always-raising stub). GEFS is the FIRST link in
`forecast.fallback.get_regional_forecast`'s chain; WeatherNext 2 Mini is
the fallback.

Two reasons it is primary, both real:
* **Resolution.** 0.25deg (~27.75km) native vs WN2 Mini's 1.0deg
  (~111km). Stage 1B's terrain-based downscaling starts from this
  regional field, so a finer input is a genuine accuracy gain — the
  stated reason for the switch.
* **Automation.** Fully automated; WN2 Mini needs a human to run a Colab
  notebook and copy the export into place ahead of time.

Modules:
    client.py  — real live fetching (S3 primary, NOMADS fallback transport)
    parser.py  — GRIB2 decode + regional mean -> the §B.2 contract
    errors.py  — GEFSUnavailableError (advance the chain) /
                 GEFSParseError (a real bug, never fallen through on)

Every real API/format fact these modules rely on was confirmed by
fetching and decoding live data in-session, not from documentation — see
each module's own docstring for what was verified and how.
"""
