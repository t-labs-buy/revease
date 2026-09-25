"""Celery producer — the API enqueues pipeline work by task name without importing
worker code (one-way dependency: workers import the API's models, not vice-versa)."""

from __future__ import annotations

import logging
import uuid

from celery import Celery

from app.config import get_settings
from app.tasking import DEFAULT_QUEUE, TASK_ROUTES

log = logging.getLogger("refract.queue")

_settings = get_settings()
# No result backend on the producer — it only publishes; a backend here makes
# send_task retry the result store for ~19s when Redis is down.
producer = Celery("refract-producer", broker=_settings.redis_url)
# Must match the worker's queues (app.tasking) or tasks are never consumed.
producer.conf.task_default_queue = DEFAULT_QUEUE
producer.conf.task_routes = TASK_ROUTES
# Fail fast when the broker is down so a capture request never hangs (we log + continue).
producer.conf.broker_connection_retry_on_startup = False
producer.conf.broker_connection_max_retries = 0
producer.conf.broker_transport_options = {"socket_connect_timeout": 1, "socket_timeout": 1}
producer.conf.task_publish_retry = False  # don't retry the publish when the broker is down


def _send(task: str, args: list) -> None:
    """Publish a task on a short-lived connection that fails fast when the broker is
    down, so a capture/render request never hangs (we log + continue)."""
    try:
        with producer.connection_for_write(connect_timeout=2) as conn:
            producer.send_task(task, args=args, connection=conn, retry=False)
    except Exception as e:  # pragma: no cover - broker availability
        log.warning("could not enqueue %s%s: %s", task, args, e)


def enqueue_understanding(session_id: str) -> None:
    """Fire the understanding pipeline. Each request gets its own token so the
    worker can tell a redelivered duplicate from a genuinely new request."""
    _send("refract.pipeline.run", [session_id, uuid.uuid4().hex])


def enqueue_render(render_job_id: str) -> None:
    """Fire a video render (export-time only)."""
    _send("refract.render.run", [render_job_id])


def enqueue_autoedit(job_id: str) -> None:
    """Fire a smart auto-edit (speed-up + zoom) of the raw recording."""
    _send("refract.autoedit.run", [job_id])


def enqueue_voice_preview(voice_id: str) -> None:
    """Synthesize a voice sample clip (cached)."""
    _send("refract.tts.preview", [voice_id])


def enqueue_voice_track(project_id: str, voice_id: str, speed: float) -> None:
    """Build a project's narration preview track in a given voice (cached)."""
    _send("refract.voice.track", [project_id, voice_id, speed])


def enqueue_document_generate(
    project_id: str, doc_version: int, skill_id: str | None, instruction: str | None
) -> None:
    """Write the AI documentation for a project (worker: snapshots need ffmpeg)."""
    _send("refract.document.generate", [project_id, doc_version, skill_id, instruction])


def enqueue_document_snapshot(project_id: str, step_id: str, t_seconds: float) -> None:
    """Re-grab one doc step's snapshot at a different moment of the recording."""
    _send("refract.document.snapshot", [project_id, step_id, float(t_seconds)])
