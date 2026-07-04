"""Pipeline orchestrator: Capture Session -> Workflow Graph.

Stages (media -> whisper -> merge -> extract) each get a Job row keyed
(session_id, stage, version) so re-runs are idempotent — a stage already `done`
for this version is skipped, and the graph is upserted by (project, version) so a
re-run never produces a duplicate. FFmpeg/Whisper failures are logged with stderr
and the pipeline degrades to whatever media it has (screenshots/events)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import CaptureSession, Event, Job, MediaAsset, Transcript, WorkflowGraphRow
from app.storage import store
from worker.pipeline import media as media_stage
from worker.pipeline.extract import build_graph
from worker.pipeline.providers import Transcript as TranscriptData
from worker.pipeline.providers import Word, transcribe
from worker.pipeline.segment import segment

log = logging.getLogger("refract.pipeline.run")

STAGES = ("media", "whisper", "merge", "extract")


def _job(db, session_id: str, stage: str, version: int) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.session_id == session_id, Job.stage == stage, Job.version == version
        )
    )
    if job is None:
        job = Job(session_id=session_id, stage=stage, version=version, status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


def _duration_s(sess: CaptureSession, events: list[dict], keyframes, transcript) -> float:
    if sess.duration_ms:
        return sess.duration_ms / 1000.0
    if events:
        return max(e["t_ms"] for e in events) / 1000.0
    if keyframes:
        return max(t for t, _ in keyframes)
    if transcript.words:
        return transcript.words[-1].t_end
    return 0.0


def run_pipeline(session_id: str) -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        sess = db.get(CaptureSession, session_id)
        if sess is None:
            # Permanent condition (e.g. a stale queued message for a deleted session).
            # Return gracefully so the task acks instead of retrying forever.
            log.warning("session %s not found; skipping", session_id)
            return {"session_id": session_id, "skipped": "session not found"}

        # One version per run = max existing graph version for the project + 1.
        max_v = db.scalar(
            select(func.max(WorkflowGraphRow.version)).where(
                WorkflowGraphRow.project_id == sess.project_id
            )
        )
        version = (max_v or 0) + 1
        sess.status = "processing"
        db.commit()

        # ---- media stage: ffmpeg keyframes + audio demux ---------------------
        job = _job(db, session_id, "media", version)
        if job.status != "done":
            job.status = "running"
            job.attempts += 1
            db.commit()
            try:
                _run_media(db, sess)
                job.status = "done"
                db.commit()
            except Exception as e:  # never fatal — degrade to screenshots/events
                log.exception("media stage error")
                job.status = "error"
                job.error_json = {"error": str(e)}
                db.commit()

        # ---- whisper stage ---------------------------------------------------
        job = _job(db, session_id, "whisper", version)
        if job.status != "done":
            job.status = "running"
            job.attempts += 1
            db.commit()
            try:
                _run_whisper(db, sess)
                job.status = "done"
                db.commit()
            except Exception as e:
                log.exception("whisper stage error")
                job.status = "error"
                job.error_json = {"error": str(e)}
                db.commit()

        # ---- gather + merge/segment -----------------------------------------
        job = _job(db, session_id, "merge", version)
        events = [
            {
                "seq": e.seq,
                "type": e.type,
                "t_ms": e.t_ms,
                "selector": e.selector,
                "text": e.text,
                "bbox": e.bbox_json,
            }
            for e in db.scalars(
                select(Event).where(Event.session_id == session_id).order_by(Event.seq)
            )
        ]
        transcript = _load_transcript(db, session_id)
        keyframes = _load_keyframes(db, session_id)
        screenshots_by_seq = _load_screenshots(db, session_id)

        # Apply trim — keep-ranges (from split/delete) take precedence, else a single
        # in/out window. Keep only events/keyframes/words inside the kept region(s).
        keep = sess.keep_ranges_json
        if keep:
            rngs = [(a / 1000.0, b / 1000.0) for a, b in keep if b > a]
            in_keep = lambda t: any(a <= t <= b for a, b in rngs)  # noqa: E731
            events = [e for e in events if in_keep(e["t_ms"] / 1000.0)]
            keyframes = [(t, k) for (t, k) in keyframes if in_keep(t)]
            transcript.words = [w for w in transcript.words if in_keep(w.t_start)]
            duration = max((b for _, b in rngs), default=0.0)
        elif sess.trim_start_ms is not None and sess.trim_end_ms is not None:
            t0, t1 = sess.trim_start_ms, sess.trim_end_ms
            events = [e for e in events if t0 <= e["t_ms"] <= t1]
            keyframes = [(t, k) for (t, k) in keyframes if t0 / 1000.0 <= t <= t1 / 1000.0]
            transcript.words = [w for w in transcript.words if t0 / 1000.0 <= w.t_start <= t1 / 1000.0]
            duration = (t1 - t0) / 1000.0
        else:
            duration = _duration_s(sess, events, keyframes, transcript)

        candidate_steps = segment(
            events, transcript, keyframes, screenshots_by_seq, duration, sess.telemetry
        )
        job.status = "done"
        db.commit()

        # ---- extract + persist (idempotent upsert by project+version) --------
        job = _job(db, session_id, "extract", version)
        job.status = "running"
        job.attempts += 1
        db.commit()
        title = f"Workflow ({len(candidate_steps)} steps)"
        graph = build_graph(
            candidate_steps,
            workflow_id=f"wf_{session_id[:8]}",
            title=title,
            version=version,
        )
        _persist_graph(db, sess.project_id, version, graph)
        job.status = "done"
        db.commit()

        # Give the project a meaningful name from the transcript (replaces the
        # placeholder "Screen Recording · …" / uploaded file name). Skipped when
        # there's no speech to title from.
        try:
            from app.models import Project
            from app.rewrite import generate_title

            new_name = generate_title(transcript.text)
            if new_name:
                proj = db.get(Project, sess.project_id)
                if proj is not None:
                    proj.name = new_name
                    db.commit()
        except Exception:
            log.warning("project auto-title failed; keeping current name")

        sess.status = "ready"
        db.commit()
        return {"session_id": session_id, "version": version, "steps": len(graph["steps"])}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
def _run_media(db, sess: CaptureSession) -> None:
    video = db.scalar(
        select(MediaAsset).where(
            MediaAsset.session_id == sess.id, MediaAsset.kind == "raw_video"
        )
    )
    if not video:
        return  # extension session: screenshots are the keyframes
    video_path = store.local_path(video.storage_key)
    if not video_path.exists():
        log.warning("raw_video missing on disk: %s", video.storage_key)
        return

    # Normalize the raw recording/upload into a seekable faststart MP4. Browser
    # recordings are header-less WebM (no duration → un-seekable, breaks trim +
    # auto-edit). Repoint the raw_video asset so the editor preview, trim UI,
    # auto-edit and render all use the well-formed MP4. Idempotent on re-process.
    try:
        norm_key = f"sessions/{sess.id}/source.mp4"
        norm = media_stage.normalize_video(video_path, store.local_path(norm_key))
        if norm is not None:
            video.storage_key = norm_key
            db.commit()
            video_path = store.local_path(norm_key)
    except media_stage.FFmpegError:
        log.warning("video normalize failed; continuing with the original container")

    # audio demux (best-effort)
    audio_key = f"sessions/{sess.id}/audio.wav"
    try:
        out = media_stage.demux_audio(video_path, store.local_path(audio_key))
        if out is not None and not db.scalar(
            select(MediaAsset).where(
                MediaAsset.session_id == sess.id, MediaAsset.kind == "audio"
            )
        ):
            db.add(MediaAsset(session_id=sess.id, kind="audio", storage_key=audio_key))
            db.commit()
    except media_stage.FFmpegError:
        log.warning("audio demux failed; continuing")

    # keyframes
    frames = media_stage.extract_keyframes(video_path, store.local_path(f"sessions/{sess.id}/frames"))
    # clear any prior frame assets for a clean re-run
    for old in db.scalars(
        select(MediaAsset).where(MediaAsset.session_id == sess.id, MediaAsset.kind == "frame")
    ):
        db.delete(old)
    for kf in frames:
        key = f"sessions/{sess.id}/frames/{kf.path.name}"
        db.add(MediaAsset(session_id=sess.id, kind="frame", storage_key=key, meta_json={"t": kf.t}))
    db.commit()


def _run_whisper(db, sess: CaptureSession) -> None:
    audio = db.scalar(
        select(MediaAsset).where(MediaAsset.session_id == sess.id, MediaAsset.kind == "audio")
    )
    audio_path = str(store.local_path(audio.storage_key)) if audio else None
    result = transcribe(audio_path)
    existing = db.scalar(select(Transcript).where(Transcript.session_id == sess.id))
    if existing:
        db.delete(existing)
        db.commit()
    db.add(
        Transcript(
            session_id=sess.id,
            words_json=[{"w": w.w, "t_start": w.t_start, "t_end": w.t_end} for w in result.words],
            text=result.text,
            provider=result.provider,
        )
    )
    db.commit()


def _load_transcript(db, session_id: str) -> TranscriptData:
    row = db.scalar(select(Transcript).where(Transcript.session_id == session_id))
    if not row:
        return TranscriptData(provider="none")
    words = [Word(w=x["w"], t_start=x["t_start"], t_end=x["t_end"]) for x in (row.words_json or [])]
    return TranscriptData(words=words, text=row.text or "", provider=row.provider)


def _load_keyframes(db, session_id: str) -> list[tuple[float, str]]:
    frames = db.scalars(
        select(MediaAsset).where(MediaAsset.session_id == session_id, MediaAsset.kind == "frame")
    )
    kf = [((a.meta_json or {}).get("t", 0.0), a.storage_key) for a in frames]
    return sorted(kf, key=lambda x: x[0])


def _load_screenshots(db, session_id: str) -> dict[int, str]:
    shots = db.scalars(
        select(MediaAsset).where(
            MediaAsset.session_id == session_id, MediaAsset.kind == "screenshot"
        )
    )
    out: dict[int, str] = {}
    for a in shots:
        seq = (a.meta_json or {}).get("seq")
        if seq is not None:
            out[int(seq)] = a.storage_key
    return out


def _persist_graph(db, project_id: str, version: int, graph: dict[str, Any]) -> None:
    """Upsert by (project_id, version) so a re-run never creates a duplicate graph."""
    existing = db.scalar(
        select(WorkflowGraphRow).where(
            WorkflowGraphRow.project_id == project_id, WorkflowGraphRow.version == version
        )
    )
    if existing:
        existing.graph_json = graph
    else:
        db.add(WorkflowGraphRow(project_id=project_id, version=version, graph_json=graph))
    db.commit()
