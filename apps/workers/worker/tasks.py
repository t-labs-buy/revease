"""Worker tasks. V1-P0 ships a health ping; the AI pipeline (media/whisper/ocr/
extract/render) attaches here in Phase 2+ with idempotency keyed by
(session_id, stage, version)."""

from __future__ import annotations

from worker.celery_app import app

# A new pipeline request that arrives while another run of the same recording is
# live re-queues itself every DEFER_COUNTDOWN_S seconds, for up to a day.
DEFER_COUNTDOWN_S = 30
DEFER_MAX_WAITS = 24 * 3600 // DEFER_COUNTDOWN_S


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
def run_understanding(self, session_id: str, token: str | None = None):  # noqa: ANN001
    """Understanding pipeline: session -> schema-valid Workflow Graph.
    Idempotent per (session, stage, version); transient errors retry with backoff.
    A new request arriving while another run is live waits (re-queued every 30s)
    instead of starting a second encode of the same file."""
    from worker.pipeline.run import run_pipeline

    try:
        result = run_pipeline(session_id, token)
    except Exception as exc:
        raise self.retry(exc=exc)
    if isinstance(result, dict) and result.get("deferred"):
        # NB: retry(max_retries=DEFER_MAX_WAITS) means "use the task default" (3), not
        # "unlimited" — that let a waiting request give up before the stale
        # run it was waiting on could be taken over. Wait up to a day.
        raise self.retry(countdown=DEFER_COUNTDOWN_S, max_retries=DEFER_MAX_WAITS)
    return result


@app.task(name="refract.render.run", bind=True, max_retries=2, default_retry_delay=5)
def run_render_task(self, render_job_id: str):  # noqa: ANN001
    """Render (or re-render) a video project's MP4 on export."""
    import importlib
    import worker.pipeline.render
    importlib.reload(worker.pipeline.render)
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

    key = f"previews/{voice_id}.wav"
    dst = store.local_path(key)
    if store.exists(key):
        return {"voice_id": voice_id, "cached": True}
    r = synth_step(PREVIEW_TEXT, media_root=store.root, voice_id=voice_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.local_path(r.storage_key), dst)
    store.commit(key)
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


@app.task(
    name="refract.document.generate",
    bind=True,
    max_retries=1,
    default_retry_delay=5,
    acks_late=True,
)
def document_generate_task(self, project_id: str, doc_version: int, skill_id=None, instruction=None):  # noqa: ANN001
    """Write the AI documentation for a project and grab a snapshot per step.
    Idempotent per (project, doc_version); a stale redelivery drops itself."""
    from worker.pipeline.docgen_job import run_document_generate

    try:
        return run_document_generate(project_id, int(doc_version), skill_id, instruction)
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(name="refract.document.snapshot", bind=True, max_retries=1, default_retry_delay=3)
def document_snapshot_task(self, project_id: str, step_id: str, t_seconds: float):  # noqa: ANN001
    """Re-grab one doc step's snapshot at a chosen moment of the recording."""
    from worker.pipeline.docgen_job import run_document_snapshot

    try:
        return run_document_snapshot(project_id, step_id, float(t_seconds))
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(name="refract.maintenance.retention")
def retention_task(dry_run: bool = False):  # noqa: ANN001
    """Hourly sweep of regenerable/superseded media (see app.retention)."""
    from app.config import get_settings
    from app.retention import run_retention

    if not get_settings().retention_enabled:
        return {"skipped": "retention disabled"}
    return run_retention(dry_run=bool(dry_run))
