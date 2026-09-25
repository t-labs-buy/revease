"""Pipeline orchestrator: Capture Session -> Workflow Graph.

Stages (media -> whisper -> merge -> extract) each get a Job row keyed
(session_id, stage, version) so re-runs are idempotent — a stage already `done`
for this version is skipped, and the graph is upserted by (project, version) so a
re-run never produces a duplicate. FFmpeg/Whisper failures are logged with stderr
and the pipeline degrades to whatever media it has (screenshots/events)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import (
    AutoRecordRun,
    CaptureSession,
    Event,
    Job,
    MediaAsset,
    Transcript,
    WorkflowGraphRow,
)
from app.storage import store
from worker.pipeline import media as media_stage
from worker.pipeline.extract import build_graph, build_graph_auto
from worker.pipeline.narrate import narrate_steps
from worker.pipeline.progress import Heartbeat, Reporter, fmt_clock
from worker.pipeline.providers import Transcript as TranscriptData
from worker.pipeline.providers import Word, transcribe
from worker.pipeline.segment import segment
from worker.pipeline.segment_auto import segment_auto

log = logging.getLogger("refract.pipeline.run")

STAGES = ("media", "whisper", "merge", "extract")


def _live_duplicate(db, session_id: str) -> Job | None:
    """A stage of this session that is running with a fresh heartbeat. A
    redelivered (or double-clicked) pipeline task must not start a second copy
    of a long encode that is still making progress; a stale one is taken over."""
    stale_after = timedelta(seconds=get_settings().pipeline_stale_after_s)
    now = datetime.now(timezone.utc)
    for job in db.scalars(select(Job).where(Job.session_id == session_id, Job.status == "running")):
        updated = job.updated_at if job.updated_at.tzinfo else job.updated_at.replace(tzinfo=timezone.utc)
        if now - updated < stale_after:
            return job
    return None


def _start(db, job: Job, message: str) -> Reporter:
    job.status = "running"
    job.attempts += 1
    job.progress = 0.0
    job.message = message
    job.started_at = datetime.now(timezone.utc)
    job.error_json = None
    db.commit()
    return Reporter(Job, job.id)


def _finish(db, job: Job, message: str = "Done") -> None:
    job.status = "done"
    job.progress = 1.0
    job.message = message
    db.commit()


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


def run_pipeline(session_id: str, token: str | None = None) -> dict[str, Any]:
    init_db()
    db = SessionLocal()
    try:
        sess = db.get(CaptureSession, session_id)
        if sess is None:
            # Permanent condition (e.g. a stale queued message for a deleted session).
            # Return gracefully so the task acks instead of retrying forever.
            log.warning("session %s not found; skipping", session_id)
            return {"session_id": session_id, "skipped": "session not found"}

        live = _live_duplicate(db, session_id)
        if live is not None:
            if token and token != sess.pipeline_token:
                # A new request (re-trim / reprocess): wait for the live run to end.
                log.info("session %s: new request waits for the running %s stage", session_id, live.stage)
                return {"session_id": session_id, "deferred": True, "stage": live.stage}
            log.warning("session %s: %s stage already running (heartbeat %s); dropping duplicate delivery",
                        session_id, live.stage, live.updated_at)
            return {"session_id": session_id, "skipped": "already running", "stage": live.stage}
        sess.pipeline_token = token

        # One version per run = max existing graph version for the project + 1.
        max_v = db.scalar(
            select(func.max(WorkflowGraphRow.version)).where(
                WorkflowGraphRow.project_id == sess.project_id
            )
        )
        version = (max_v or 0) + 1
        sess.status = "processing"
        db.commit()

        # Auto Record: the agent's own decision log is the authoritative step source,
        # and the transcript is user-supplied text (no spoken audio to transcribe).
        is_auto = sess.source_type == "auto"
        auto_run = (
            db.scalar(select(AutoRecordRun).where(AutoRecordRun.session_id == session_id))
            if is_auto
            else None
        )
        if auto_run is not None:
            auto_run.status = "processing"
            db.commit()

        # ---- media stage: ffmpeg keyframes + audio demux ---------------------
        job = _job(db, session_id, "media", version)
        if job.status != "done":
            report = _start(db, job, "Preparing video…")
            try:
                with Heartbeat(Job, job.id):
                    _run_media(db, sess, report)
                _finish(db, job, "Video ready")
            except Exception as e:  # never fatal — degrade to screenshots/events
                log.exception("media stage error")
                job.status = "error"
                job.error_json = {"error": str(e)}
                job.message = "Video conversion failed — continuing with what we have"
                db.commit()

        # ---- whisper stage ---------------------------------------------------
        job = _job(db, session_id, "whisper", version)
        if job.status != "done":
            report = _start(db, job, "Transcribing speech…")
            try:
                with Heartbeat(Job, job.id):
                    if is_auto:
                        _write_user_transcript(db, sess, auto_run.transcript_text if auto_run else "")
                    else:
                        _run_whisper(db, sess, report)
                _finish(db, job, "Transcript ready")
            except Exception as e:
                log.exception("whisper stage error")
                job.status = "error"
                job.error_json = {"error": str(e)}
                db.commit()

        # ---- gather + merge/segment -----------------------------------------
        job = _job(db, session_id, "merge", version)
        _start(db, job, "Finding the steps…")
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

        if is_auto:
            # Project the agent's decision log onto steps (timing from telemetry
            # events keyed by decision index), then align the transcript across them.
            events_by_index = {
                e["seq"]: {"t_ms": e["t_ms"], "bbox": e.get("bbox"), "selector": e.get("selector")}
                for e in events
            }
            agent_log = auto_run.agent_log_json if auto_run else []
            candidate_steps = segment_auto(agent_log, events_by_index, screenshots_by_seq, duration)
            narrations = narrate_steps(
                candidate_steps,
                auto_run.coverage_plan_json if auto_run else [],
                auto_run.transcript_text if auto_run else "",
            )
            for cand, narr in zip(candidate_steps, narrations):
                cand["narration_span"] = narr
        else:
            candidate_steps = segment(
                events, transcript, keyframes, screenshots_by_seq, duration, sess.telemetry
            )
        _finish(db, job, f"Found {len(candidate_steps)} steps")

        # ---- extract + persist (idempotent upsert by project+version) --------
        job = _job(db, session_id, "extract", version)
        _start(db, job, f"Labelling {len(candidate_steps)} steps with AI…")
        title = f"Workflow ({len(candidate_steps)} steps)"
        # The LLM labelling reports no progress of its own and can take minutes.
        extract_hb = Heartbeat(Job, job.id).__enter__()
        try:
            if is_auto:
                graph = build_graph_auto(
                    candidate_steps,
                    workflow_id=f"wf_{session_id[:8]}",
                    title=title,
                    version=version,
                )
            else:
                graph = build_graph(
                    candidate_steps,
                    workflow_id=f"wf_{session_id[:8]}",
                    title=title,
                    version=version,
                )
            _persist_graph(db, sess.project_id, version, graph)
            extract_hb.__exit__(None, None, None)
            _finish(db, job, "Workflow ready")
        except Exception as e:
            extract_hb.__exit__(None, None, None)
            # Unlike media/whisper, extract has no graceful degradation — without a
            # graph the project is unusable, so surface a real error instead of
            # leaving the job stuck at "running" forever (silently, on every retry).
            log.exception("extract stage error")
            job.status = "error"
            job.error_json = {"error": str(e)}
            sess.status = "error"
            if auto_run is not None:
                auto_run.status = "error"
            db.commit()
            return {"session_id": session_id, "version": version, "error": str(e)}

        # Precompute auto-zooms into the edit spec so the editor shows real zooms
        # (preview, Zoom tab, timeline row) — the render then reuses them directly.
        try:
            _precompute_zooms(db, sess, version)
        except Exception:
            log.exception("zoom precompute failed; render-time fallback still applies")

        # Give the project a meaningful name from what the recording shows (replaces
        # the placeholder "Screen Recording · …" / uploaded file name): the task the
        # speaker states, else the dominant topic, else the screens the steps
        # touched. An empty answer keeps the current name.
        try:
            from app.models import Project
            from app.titles import is_placeholder_name, suggest_title

            new_name, source = suggest_title(transcript.text, graph.get("steps", []))
            proj = db.get(Project, sess.project_id)
            # An AI title may replace any name; the offline heuristic only replaces
            # an automatic placeholder, so it never downgrades a good name.
            if new_name and proj is not None and (source == "llm" or is_placeholder_name(proj.name)):
                proj.name = new_name
                db.commit()
        except Exception:
            log.warning("project auto-title failed; keeping current name")

        sess.status = "ready"
        if auto_run is not None:
            auto_run.status = "ready"
        db.commit()
        return {"session_id": session_id, "version": version, "steps": len(graph["steps"])}
    finally:
        db.close()


def _write_user_transcript(db, sess: CaptureSession, text: str) -> None:
    """Auto Record has no spoken audio — persist the user's supplied transcript as
    the session transcript (provider='user') so downstream titling still works."""
    existing = db.scalar(select(Transcript).where(Transcript.session_id == sess.id))
    if existing:
        db.delete(existing)
        db.commit()
    db.add(Transcript(session_id=sess.id, words_json=[], text=text or "", provider="user"))
    db.commit()


# --------------------------------------------------------------------------- #
def _run_media(db, sess: CaptureSession, report: Reporter | None = None) -> None:
    report = report or (lambda *_a, **_k: None)
    video = db.scalar(
        select(MediaAsset).where(
            MediaAsset.session_id == sess.id, MediaAsset.kind == "raw_video"
        )
    )
    if not video:
        return  # extension session: screenshots are the keyframes
    video_path = store.fetch(video.storage_key)  # S3: downloads into the media cache
    if video_path is None:
        log.warning("raw_video missing from storage: %s", video.storage_key)
        return

    # Normalize the raw recording/upload into a seekable faststart MP4. Browser
    # recordings are header-less WebM (no duration → un-seekable, breaks trim +
    # auto-edit). Repoint the raw_video asset so the editor preview, trim UI,
    # auto-edit and render all use the well-formed MP4. Idempotent on re-process.
    try:
        norm_key = f"sessions/{sess.id}/source.mp4"
        total_s = (sess.duration_ms or 0) / 1000.0
        conv = report.sub(0.0, 0.8) if isinstance(report, Reporter) else report
        conv(0.0, "Converting video…")

        def on_conv(frac: float, done_s: float) -> None:
            total = total_s or (done_s / frac if frac else 0)
            conv(frac, f"Converting video · {fmt_clock(done_s)} of {fmt_clock(total)}")

        proxy_key = f"sessions/{sess.id}/proxy.mp4"
        norm = media_stage.normalize_video(video_path, store.local_path(norm_key),
                                           duration_s=total_s, on_progress=on_conv,
                                           proxy_out=store.local_path(proxy_key))
        if norm is None:  # already a good MP4: only the preview proxy is needed
            conv(0.0, "Creating preview…")
            media_stage.make_proxy(video_path, store.local_path(proxy_key), duration_s=total_s,
                                   on_progress=lambda f, _d: conv(f, "Creating preview…"))
        store.commit(proxy_key)
        _upsert_asset(db, sess.id, "proxy", proxy_key)
        if norm is not None:
            store.commit(norm_key)
            video.storage_key = norm_key
            db.commit()
            video_path = store.local_path(norm_key)
    except media_stage.FFmpegError:
        log.warning("video normalize failed; continuing with the original container")

    # audio demux (best-effort)
    report(0.82, "Extracting audio…")
    audio_key = f"sessions/{sess.id}/audio.wav"
    try:
        out = media_stage.demux_audio(video_path, store.local_path(audio_key))
        if out is not None:
            store.commit(audio_key)
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
    report(0.88, "Capturing keyframes…")
    frames = media_stage.extract_keyframes(video_path, store.local_path(f"sessions/{sess.id}/frames"))
    store.commit_tree(f"sessions/{sess.id}/frames")
    # clear any prior frame assets for a clean re-run
    for old in db.scalars(
        select(MediaAsset).where(MediaAsset.session_id == sess.id, MediaAsset.kind == "frame")
    ):
        db.delete(old)
    for kf in frames:
        key = f"sessions/{sess.id}/frames/{kf.path.name}"
        db.add(MediaAsset(session_id=sess.id, kind="frame", storage_key=key, meta_json={"t": kf.t}))
    db.commit()


def _upsert_asset(db, session_id: str, kind: str, key: str) -> None:
    if not db.scalar(select(MediaAsset).where(MediaAsset.session_id == session_id, MediaAsset.kind == kind)):
        db.add(MediaAsset(session_id=session_id, kind=kind, storage_key=key))
        db.commit()


def _run_whisper(db, sess: CaptureSession, report: Reporter | None = None) -> None:
    audio = db.scalar(
        select(MediaAsset).where(MediaAsset.session_id == sess.id, MediaAsset.kind == "audio")
    )
    fetched = store.fetch(audio.storage_key) if audio else None
    audio_path = str(fetched) if fetched else None
    total_s = (sess.duration_ms or 0) / 1000.0

    def on_words(frac: float, done_s: float) -> None:
        if report:
            report(frac, f"Transcribing speech · {fmt_clock(done_s)} of {fmt_clock(total_s or done_s / max(frac, 1e-6))}")

    result = transcribe(audio_path, on_progress=on_words)
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


def _precompute_zooms(db, sess: CaptureSession, version: int) -> None:
    """Materialize click/motion auto-zooms into the project's edit spec right after
    processing, so the editor previews real zooms and the render reuses them.
    Scenes with a manual zoom or an explicit opt-out (auto=False) are untouched."""
    from sqlalchemy.orm.attributes import flag_modified

    from app.diff import migrate_edit_spec
    from app.editspec import build_edit_spec
    from app.models import VideoProject
    from worker.pipeline.autoedit import _motion_centroid, probe_dims
    from worker.pipeline.render import _click_points

    video = db.scalar(
        select(MediaAsset).where(MediaAsset.session_id == sess.id, MediaAsset.kind == "raw_video")
    )
    video_path = store.fetch(video.storage_key) if video else None
    if video_path is None:
        return
    graph = db.scalar(
        select(WorkflowGraphRow).where(
            WorkflowGraphRow.project_id == sess.project_id, WorkflowGraphRow.version == version
        )
    )
    if graph is None:
        return

    # Build (or migrate) the video project spec — mirrors the API's lazy build so
    # the editor and this stage always agree on the spec version.
    vp = db.scalar(select(VideoProject).where(VideoProject.project_id == sess.project_id))
    if vp is None:
        vp = VideoProject(
            project_id=sess.project_id,
            graph_version=version,
            edit_spec_json=build_edit_spec(graph.graph_json, sess.viewport_json),
        )
        db.add(vp)
        db.commit()
        db.refresh(vp)
    elif vp.graph_version != version:
        old = db.scalar(
            select(WorkflowGraphRow).where(
                WorkflowGraphRow.project_id == sess.project_id,
                WorkflowGraphRow.version == vp.graph_version,
            )
        )
        vp.edit_spec_json = (
            migrate_edit_spec(vp.edit_spec_json, old.graph_json, graph.graph_json, sess.viewport_json)
            if old is not None
            else build_edit_spec(graph.graph_json, sess.viewport_json)
        )
        vp.graph_version = version
        flag_modified(vp, "edit_spec_json")
        db.commit()

    spec = vp.edit_spec_json
    # Auto zooms are opt-in (spec.motion_zoom, off for new projects): only
    # materialize them when the user has the toggle on — same gate the render uses.
    if not spec.get("motion_zoom", True):
        log.info("zoom precompute: motion_zoom off; no auto zooms added")
        return
    clicks = _click_points(db, sess.id)
    vdims = probe_dims(video_path)
    zoomed = 0
    for s in spec.get("segments", []):
        z = s.get("zoom") or {}
        if z.get("enabled") or z.get("auto") is False:
            continue  # manual zoom, already computed, or explicit user opt-out
        t0ms = s.get("source_start_ms", 0)
        t1ms = max(s.get("source_end_ms", 0), t0ms + 600)
        hit = next((c for c in clicks if t0ms - 250 <= c[0] <= t1ms), None)
        if hit:
            cx, cy, scale = hit[1], hit[2], 1.6
        else:
            cx, cy, scale = _motion_centroid(video_path, t0ms / 1000.0, t1ms / 1000.0, vdims)
        if scale > 1.0:
            s["zoom"] = {
                "enabled": True,
                "scale": round(min(1.8, scale), 3),
                "cx": cx,
                "cy": cy,
                "speed": 3,
                "auto": True,
            }
            zoomed += 1
    if zoomed:
        flag_modified(vp, "edit_spec_json")
        db.commit()
    log.info("zoom precompute: %d/%d scenes zoomed", zoomed, len(spec.get("segments", [])))


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
