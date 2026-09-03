"""Usage tracking — counts of videos generated and screens recorded.

`record_event` is best-effort by design: it opens its own short-lived session
and swallows every failure, so tracking can never break the render, capture,
or request it is measuring. Called from both the API and Celery workers (which
share SessionLocal).
"""

from __future__ import annotations

import logging

from app.db import SessionLocal
from app.models import UsageEvent

log = logging.getLogger(__name__)

KINDS = ("video", "recording", "upload")


def record_event(kind: str, user_id: str | None = None, duration_ms: int | None = None) -> None:
    """Append one usage event. Never raises."""
    if kind not in KINDS:
        log.warning("unknown usage event kind %r; not recorded", kind)
        return
    try:
        db = SessionLocal()
        try:
            db.add(UsageEvent(kind=kind, user_id=user_id, duration_ms=duration_ms))
            db.commit()
        finally:
            db.close()
    except Exception:
        log.warning("failed to record usage event %r", kind, exc_info=True)
