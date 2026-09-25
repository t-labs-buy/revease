"""Live progress for long-running work (pipeline stages, documents, renders).

Why a separate short DB session per write: the stage code holds its own session
and transaction; progress lines are written from inside an ffmpeg/whisper loop
(and from a heartbeat thread), so each update is a tiny standalone UPDATE that
commits immediately and never entangles with the caller's unit of work.

Why a heartbeat: `updated_at` is how a redelivered or re-requested run tells a
live stage (touched in the last few minutes) from one whose worker died. Some
steps (an LLM call, a model load) report no progress for minutes, so a thread
keeps touching the row while the stage runs.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import update

from app.db import SessionLocal

log = logging.getLogger("refract.pipeline.progress")

ProgressFn = Callable[[float | None, str | None], None]


def _write(model: Any, row_id: str, values: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.execute(update(model).where(model.id == row_id).values(**values))
        db.commit()
    except Exception as e:  # progress is best effort; never fail the work over it
        log.debug("progress write for %s %s failed: %s", model.__name__, row_id, e)
        db.rollback()
    finally:
        db.close()


class Reporter:
    """Callable(progress 0..1 | None, message | None). Throttled: at most one
    write per `min_interval` seconds, except when the message changes or the
    value reaches 1.0, so a tight ffmpeg loop can call it on every line."""

    def __init__(self, model: Any, row_id: str, *, min_interval: float = 2.0, scale: tuple[float, float] = (0.0, 1.0)):
        self.model = model
        self.row_id = row_id
        self.min_interval = min_interval
        self.lo, self.hi = scale
        self._last_t = 0.0
        self._last_msg: str | None = None

    def sub(self, lo: float, hi: float) -> "Reporter":
        """A reporter for a slice of this one's range (e.g. snapshots = 40..95%)."""
        span = self.hi - self.lo
        return Reporter(self.model, self.row_id, min_interval=self.min_interval,
                        scale=(self.lo + span * lo, self.lo + span * hi))

    def __call__(self, progress: float | None = None, message: str | None = None) -> None:
        now = time.monotonic()
        changed = message is not None and message != self._last_msg
        final = progress is not None and progress >= 1.0
        if not (changed or final or now - self._last_t >= self.min_interval):
            return
        self._last_t = now
        values: dict[str, Any] = {}
        if progress is not None:
            p = min(1.0, max(0.0, float(progress)))
            values["progress"] = round(self.lo + (self.hi - self.lo) * p, 4)
        if message is not None:
            values["message"] = message[:300]
            self._last_msg = message
        if values:
            _write(self.model, self.row_id, values)


class Heartbeat:
    """Touch `updated_at` every `every` seconds while the block runs."""

    def __init__(self, model: Any, row_id: str, every: float = 20.0):
        self.model = model
        self.row_id = row_id
        self.every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            _write(self.model, self.row_id, {"updated_at": datetime.now(timezone.utc)})

    def __enter__(self) -> "Heartbeat":
        self._thread = threading.Thread(target=self._loop, name=f"heartbeat-{self.row_id[:8]}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def fmt_clock(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
