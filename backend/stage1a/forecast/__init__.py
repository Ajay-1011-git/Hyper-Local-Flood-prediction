"""Regional forecast acquisition orchestration: source chain, persistence, Celery task.

Not tied to any one model — `gencast/` was renamed here once the legacy
GenCast live-inference path was removed (no TPU/JAX credentials available;
see `fallback.py`'s module docstring for the current source chain).
"""
