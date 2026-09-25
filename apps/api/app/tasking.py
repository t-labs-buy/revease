"""Task routing + broker settings shared by the API (producer) and the worker
(consumer), so both sides agree on which queue a task lives on.

Why two queues: a long recording's normalize/transcribe/render can occupy a
worker slot for an hour. On one shared queue that blocks the quick jobs behind
it (a doc snapshot re-grab, a voice preview). `media` gets its own worker pool
sized for CPU; `default` stays responsive.

Why the visibility timeout matters: with `acks_late`, Redis hands an
unacknowledged task to another consumer once this timeout passes. Celery's 1h
default is shorter than a long normalize, which produced duplicate ffmpeg runs
writing the same file.
"""

from __future__ import annotations

from app.config import get_settings

MEDIA_QUEUE = "media"
DEFAULT_QUEUE = "default"

TASK_ROUTES = {
    "refract.pipeline.run": {"queue": MEDIA_QUEUE},
    "refract.render.run": {"queue": MEDIA_QUEUE},
    "refract.autoedit.run": {"queue": MEDIA_QUEUE},
    # everything else (document, snapshot, TTS preview, voice track, ping) -> default
}


def broker_transport_options() -> dict:
    return {"visibility_timeout": get_settings().celery_visibility_timeout_s}
