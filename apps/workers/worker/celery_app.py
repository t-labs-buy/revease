"""Celery app. Two queues by resource profile (see app.tasking): `media` for
long CPU-bound work (pipeline, render, auto-edit) and `default` for quick jobs.
Run a worker per queue in production so a long encode never blocks a snapshot:

    celery -A worker.celery_app worker -Q media   -c 1
    celery -A worker.celery_app worker -Q default -c 3
"""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import worker_process_init

REDIS_URL = os.environ.get("REFRACT_REDIS_URL", "redis://localhost:6379/0")

app = Celery("refract", broker=REDIS_URL, backend=REDIS_URL)
from app.config import get_settings  # noqa: E402
from app.tasking import DEFAULT_QUEUE, TASK_ROUTES, broker_transport_options  # noqa: E402

_settings = get_settings()

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_default_queue=DEFAULT_QUEUE,
    task_routes=TASK_ROUTES,
    broker_transport_options=broker_transport_options(),
    result_backend_transport_options=broker_transport_options(),
    # Take one task at a time: a prefetched second recording would otherwise sit
    # reserved (and invisible to other workers) behind a long encode.
    worker_prefetch_multiplier=1,
    # Run by the beat scheduler embedded in the light worker (`-B`); see compose.
    beat_schedule={
        "retention": {
            "task": "refract.maintenance.retention",
            "schedule": float(_settings.retention_interval_s),
        },
    },
)


@worker_process_init.connect
def _init_langfuse(**_kwargs):
    """Instrument each prefork worker process so Anthropic calls are traced."""
    from app.tracing import init_tracing

    init_tracing()


# Import tasks so they register.
from worker import tasks  # noqa: E402,F401
