"""Worker tasks. V1-P0 ships a health ping; the AI pipeline (media/whisper/ocr/
extract/render) attaches here in Phase 2+ with idempotency keyed by
(session_id, stage, version)."""

from __future__ import annotations

from worker.celery_app import app


@app.task(name="refract.ping")
def ping() -> str:
    """Liveness check — returns 'pong' so the broker round-trip can be verified."""
    return "pong"


@app.task(
    name="refract.pipeline.run",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def run_understanding(self, session_id: str):  # noqa: ANN001
    """Understanding pipeline: session -> schema-valid Workflow Graph.
    Idempotent per (session, stage, version); transient errors retry with backoff."""
    from worker.pipeline.run import run_pipeline

    try:
        return run_pipeline(session_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(name="refract.render.run", bind=True, max_retries=2, default_retry_delay=5)
def run_render_task(self, render_job_id: str):  # noqa: ANN001
    """Render (or re-render) a video project's MP4 on export."""
    from worker.pipeline.render import run_render

    try:
        return run_render(render_job_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(name="refract.tts.preview")
def tts_preview_task(voice_id: str):  # noqa: ANN001
    """Synthesize a short sample of a voice into previews/<voice_id>.wav (cached)."""
    import shutil

    from app.storage import store
    from app.voices import PREVIEW_TEXT
    from worker.pipeline.tts import synth_step

    dst = store.local_path(f"previews/{voice_id}.wav")
    if dst.exists():
        return {"voice_id": voice_id, "cached": True}
    r = synth_step(PREVIEW_TEXT, media_root=store.root, voice_id=voice_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.local_path(r.storage_key), dst)
    return {"voice_id": voice_id, "key": f"previews/{voice_id}.wav"}


@app.task(name="refract.voice.track")
def voice_track_task(project_id: str, voice_id: str, speed: float):  # noqa: ANN001
    """Build the narration-only preview track for a project in the chosen voice."""
    from worker.pipeline.voicetrack import build_voice_track

    return build_voice_track(project_id, voice_id, float(speed))


@app.task(name="refract.autoedit.run", bind=True, max_retries=1, default_retry_delay=5)
def run_autoedit_task(self, job_id: str):  # noqa: ANN001
    """Smart auto-edit: speed up silent stretches + zoom on motion, from the raw video."""
    from worker.pipeline.autoedit_job import run_autoedit

    try:
        return run_autoedit(job_id)
    except Exception as exc:
        raise self.retry(exc=exc)
