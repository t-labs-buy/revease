"""Celery app. Queues split by resource profile (media/ml/llm/render) land in
Phase 2+; V1-P0 just proves the broker wiring with a ping task."""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import worker_process_init

REDIS_URL = os.environ.get("REFRACT_REDIS_URL", "redis://localhost:6379/0")

app = Celery("refract", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_default_queue="default",
)


@worker_process_init.connect
def _init_langfuse(**_kwargs):
    """Instrument each prefork worker process so Anthropic calls are traced."""
    from app.tracing import init_tracing

    init_tracing()


# Import tasks so they register.
from worker import tasks  # noqa: E402,F401
