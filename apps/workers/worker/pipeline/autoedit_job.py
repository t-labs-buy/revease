"""Orchestrates an AutoEditJob: find the source video, analyze, render, persist."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AutoEditJob, CaptureSession, MediaAsset, Transcript
from app.storage import store
from worker.pipeline import autoedit

log = logging.getLogger("refract.pipeline.autoedit_job")


def _find_source_video(db, project_id: str):
    """Return (video_path, session_id) for the project's raw video, or (None, None)."""
    for sess in db.scalars(
        select(CaptureSession).where(CaptureSession.project_id == project_id)
    ):
        asset = db.scalar(
            select(MediaAsset).where(
                MediaAsset.session_id == sess.id, MediaAsset.kind == "raw_video"
            )
        )
        if asset:
            p = store.local_path(asset.storage_key)
            if p.exists():
                return p, sess.id
    return None, None


def run_autoedit(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.get(AutoEditJob, job_id)
        if job is None:
            log.warning("autoedit job %s not found; skipping", job_id)
            return {"job_id": job_id, "skipped": "not found"}
        job.status = "running"
        db.commit()

        opts = job.options_json or {}
        preset = opts.get("aggressiveness", "balanced")
        want_captions = opts.get("captions", True)
        want_zoom = opts.get("zoom", True)

        video, session_id = _find_source_video(db, job.project_id)
        if video is None:
            job.status = "error"
            job.error_json = {"error": "no source video for this project"}
            db.commit()
            return {"job_id": job_id, "error": "no source video"}

        analysis = autoedit.analyze(video, preset=preset, zoom=want_zoom)
        work = store.local_path(f"autoedit/{job.id}")
        work.mkdir(parents=True, exist_ok=True)

        # captions: re-time the transcript onto the sped-up timeline
        srt_path = None
        if want_captions and session_id:
            row = db.scalar(select(Transcript).where(Transcript.session_id == session_id))
            words = (row.words_json if row else None) or []
            srt = autoedit.build_srt(words, analysis.segments)
            if srt:
                srt_path = work / "captions.srt"
                srt_path.write_text(srt)

        out_key = f"autoedit/{job.id}.mp4"
        out_path = store.local_path(out_key)
        stats = autoedit.render(video, analysis, out_path, work, srt_path=srt_path)

        job.output_key = out_key
        job.stats_json = stats
        job.status = "done"
        db.commit()
        log.info("autoedit done: %s", stats)
        return {"job_id": job_id, **stats}
    except Exception as e:
        log.exception("autoedit failed")
        job = db.get(AutoEditJob, job_id)
        if job:
            job.status = "error"
            job.error_json = {"error": str(e)}
            db.commit()
        raise
    finally:
        db.close()
