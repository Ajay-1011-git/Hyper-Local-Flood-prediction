"""Celery application for Stage 1A (T1A.5).

API note (anti-hallucination rule 2): the task-definition API used here was
verified against the installed Celery 5.6.3 in-session — `celery.Celery(...)`
with `broker=`/`backend=` kwargs, the `@app.task(name=..., bind=True)`
decorator, `.delay()`, and the `task_always_eager` conf key were all
exercised before this file was written.

Redis serves as both broker and result backend, per TRD §3.2/§3.4.

Worker:
    cd backend && celery -A stage1a.celery_app.app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from stage1a.config import get_settings

_settings = get_settings()

app = Celery(
    "stage1a",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["stage1a.gencast.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A forecast run is long and expensive; don't let a lost worker silently
    # drop one, and don't let a redelivery start a second run of the same
    # window (persistence is keyed on forecast_id, so a repeat is harmless).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
