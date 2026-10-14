"""The whole-recording Generate as a background job: show the model the
recording's keyframes window by window (app.videoscript), save the timed
script on the session, and re-run understanding so the scenes are rebuilt
around it — exactly the road a pasted script takes.

Why a job and not a request: a 48-frame vision call already takes ~40 s, a
ten-minute recording is ten of them, and the public path sits behind a proxy
with a 60 s read timeout. Progress lives on a Job row (stage "script") the
editor polls, so the same heartbeat that guards the pipeline against duplicate
runs also tells `PUT /script` and `/reprocess` to wait (409) while this runs.

Failure is recorded on the row, not retried: the editor shows the message and
the user decides whether to spend the vision calls again. The script is only
written when every window produced lines, so a half-written script never
replaces the scenes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.frames import frame_jpeg
from app.llm import has_llm
from app.models import CaptureSession, Job, MediaAsset, Project, VideoProject
from app.queue import enqueue_understanding
from app.videoscript import (
    TimedLine,
    align_to_ranges,
    fit_lines,
    join_lines,
    kept_ranges,
    plan_windows,
    timed_script_text,
    window_bounds,
    write_window,
)
from app.usage_tracking import current as usage, email_for_user_id, tracked
from worker.pipeline.progress import Heartbeat, Reporter

log = logging.getLogger("refract.pipeline.videoscript_job")


def _spans(
    db, sess: CaptureSession, keyframes: list[tuple[float, str]]
) -> tuple[list[tuple[float, float]], list[list[int]] | None]:
    """(kept source windows in seconds, editor ranges to store). The same
    precedence as run_pipeline — keep ranges, else the trim window — and
    then, new here, a trim the editor holds only in the edit spec (see
    videoscript.kept_ranges), which the caller writes back to the session as
    keep ranges so the rebuilt scenes keep it. Else the whole recording."""
    if sess.keep_ranges_json:
        rngs = [(a / 1000.0, b / 1000.0) for a, b in sess.keep_ranges_json if b > a]
        if rngs:
            return rngs, None
    if sess.trim_start_ms is not None and sess.trim_end_ms is not None:
        return [(sess.trim_start_ms / 1000.0, sess.trim_end_ms / 1000.0)], None
    end_ms = int(sess.duration_ms or 0) or int(max((t for t, _ in keyframes), default=0.0) * 1000)
    vp = db.scalar(select(VideoProject).where(VideoProject.project_id == sess.project_id))
    editor = kept_ranges(vp.edit_spec_json if vp else None, end_ms)
    if editor:
        return [(a / 1000.0, b / 1000.0) for a, b in editor], editor
    return [(0.0, end_ms / 1000.0)], None


def _load_keyframes(db, session_id: str) -> list[tuple[float, str]]:
    rows = db.scalars(
        select(MediaAsset).where(MediaAsset.session_id == session_id, MediaAsset.kind == "frame")
    )
    return sorted((((a.meta_json or {}).get("t", 0.0), a.storage_key) for a in rows), key=lambda x: x[0])


def _write_script(
    db, sess: CaptureSession, report: Reporter, brief: str, mode: str
) -> tuple[list[TimedLine], list[list[int]] | None]:
    """(lines, editor keep ranges to persist or None)."""
    keyframes = _load_keyframes(db, sess.id)
    spans, editor_ranges = _spans(db, sess, keyframes)
    keyframes = [(t, k) for t, k in keyframes if any(a <= t <= b for a, b in spans)]
    if not keyframes:
        raise RuntimeError("this recording has no frames to look at")
    duration = spans[-1][1]
    project = db.get(Project, sess.project_id)
    title = (project.name if project else "") or "Product demo"

    windows = plan_windows(keyframes)
    bounds = window_bounds(windows, duration)
    parts: list[list[TimedLine]] = []
    for i, (win, (t0, t1)) in enumerate(zip(windows, bounds)):
        report(i / len(windows), f"Writing part {i + 1} of {len(windows)}…" if len(windows) > 1 else "Watching the recording…")
        frames = [(t, img) for t, key in win if (img := frame_jpeg(key)) is not None]
        if not frames:
            raise RuntimeError(f"the frames for {t0:.0f}s–{t1:.0f}s could not be read")
        prior = [ln for part in parts for ln in part][-4:]
        parts.append(
            write_window(
                frames, t0=t0, t1=t1, duration_s=duration, index=i, count=len(windows),
                title=title, brief=brief, mode=mode, prior=prior,
            )
        )
    lines = align_to_ranges(join_lines(parts, duration), spans)
    if mode == "fit" and lines:
        report(0.95, "Fitting the lines to the footage…")
        lines = fit_lines(lines, duration)
    return [ln for ln in lines if ln.text.strip()], editor_ranges


@tracked("ai_assist", "generate_narration", "narration.generated", "capture_session",
         entity_id="session_id")
def run_video_script(session_id: str, job_id: str, brief: str, mode: str = "fit", instruction: str | None = None) -> dict:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        sess = db.get(CaptureSession, session_id)
        if job is None or sess is None:
            usage().skip()
            return {"skipped": "missing job or session"}
        if job.status == "done":
            usage().skip()
            return {"skipped": "already done"}  # a redelivered copy
        owner = db.get(Project, sess.project_id)
        usage().identify(email_for_user_id(db, owner.user_id if owner else None))
        usage().set(mode=mode, custom_instruction=bool(instruction and instruction.strip()))
        job.status = "running"
        job.attempts += 1
        job.progress = 0.0
        job.message = "Reading the recording…"
        job.started_at = datetime.now(timezone.utc)
        job.error_json = None
        db.commit()
        report = Reporter(Job, job.id)
        try:
            if not has_llm():
                usage().failed("AI_NOT_CONFIGURED", stage="validate")
                raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY)")
            full_brief = f"{instruction.strip()}\n\n{brief}" if instruction and instruction.strip() else brief
            with Heartbeat(Job, job.id):
                lines, editor_ranges = _write_script(db, sess, report, full_brief, mode)
            if not lines:
                usage().failed("AI_EMPTY_RESULT")
                raise RuntimeError("the AI wrote no narration for this recording")
            sess.script_text = timed_script_text(lines)
            if editor_ranges:
                # the trim the editor held in its scenes survives the rebuild
                sess.keep_ranges_json = editor_ranges
                sess.trim_start_ms = None
                sess.trim_end_ms = None
            usage().item_count(len(lines))
            job.status = "done"
            job.progress = 1.0
            job.message = f"Wrote {len(lines)} lines — rebuilding scenes…"
            db.commit()
        except Exception as e:
            log.exception("video script for session %s failed", session_id)
            usage().failed(exc=e)  # keeps a code named above; else classified from e
            job.status = "error"
            job.error_json = {"error": str(e)[:2000]}
            job.message = str(e)[:300]
            db.commit()
            return {"error": str(e)}
        enqueue_understanding(sess.id)
        return {"lines": len(lines)}
    finally:
        db.close()
