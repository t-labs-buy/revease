"""Per-video limits (500 MB / 30 min by default) shared by every route that
accepts a recording or media upload, so the numbers and the wording stay the
same everywhere. The web app checks first (lib/limits.ts) and its recorders
stop themselves just under the limits; these checks are the backstop for old
clients, the extension and scripts.

Durations get a minute of grace: a recording stopped by the browser at 29:58
can report a few hundred ms more once the container is finalized.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings

DURATION_GRACE_MS = 60_000


def max_bytes() -> int:
    return get_settings().max_video_mb * 1024 * 1024


def split_hint() -> str:
    s = get_settings()
    return (f"Please split it into parts of at most {s.max_video_minutes} minutes / "
            f"{s.max_video_mb} MB and upload each part separately.")


def check_size(size: int | None) -> None:
    """413 when a declared upload size is over the limit."""
    if size is not None and size > max_bytes():
        raise HTTPException(
            status_code=413,
            detail=f"This file is {size / 1024 / 1024:.0f} MB — the limit is "
                   f"{get_settings().max_video_mb} MB. {split_hint()}",
        )


def duration_error(duration_ms: int | None) -> str | None:
    limit = get_settings().max_video_minutes * 60_000
    if duration_ms is not None and duration_ms > limit + DURATION_GRACE_MS:
        return (f"This video is {duration_ms / 60_000:.0f} minutes long — the limit is "
                f"{get_settings().max_video_minutes} minutes. {split_hint()}")
    return None


def check_duration(duration_ms: int | None) -> None:
    """422 when a capture reports a duration over the limit."""
    msg = duration_error(duration_ms)
    if msg:
        raise HTTPException(status_code=422, detail=msg)
