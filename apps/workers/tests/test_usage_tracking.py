"""Usage Tracker spans for the actions that finish in a worker: one usage span
per job, keyed by the job's own primary key (a Celery retry counts once), with
the owner's login as user.id; failures are marked and re-raised; skipped or
stale deliveries produce no usage span. Spans go to an in-memory exporter."""

from __future__ import annotations

import shutil
import uuid

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from PIL import Image
from sqlalchemy import select

from app import usage_tracking
from app.db import SessionLocal
from app.models import (
    AutoEditJob, CaptureSession, Document, Event, LibraryAsset, MediaAsset, Project, RenderJob, User,
    WorkflowGraphRow,
)
from app.storage import store

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    usage_tracking.set_provider(provider)
    yield exporter
    usage_tracking.set_provider(None)


def usage_spans(exporter, event: str) -> list:
    return [s for s in exporter.get_finished_spans()
            if (s.attributes or {}).get("usage.event.name") == event]


def one(exporter, event: str, *, feature: str, action: str, entity_type: str, entity_id: str,
        email: str, result: str = "success") -> dict:
    found = usage_spans(exporter, event)
    assert len(found) == 1, [s.attributes for s in exporter.get_finished_spans()]
    a = dict(found[0].attributes)
    assert (a["usage.feature"], a["usage.action"], a["usage.entity.type"], a["usage.entity.id"]) == (
        feature, action, entity_type, entity_id)
    assert a["usage.result"] == result
    assert a["user.id"] == email
    return a


def _owner(db) -> User:
    u = User(email=f"worker-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _own(db, project_id: str) -> str:
    u = _owner(db)
    db.get(Project, project_id).user_id = u.id
    db.commit()
    return u.email


# --------------------------------------------------------------------------- #
# workflow graph
# --------------------------------------------------------------------------- #
def test_pipeline_records_workflow_graph_generated(spans):
    from worker.pipeline.run import run_pipeline

    db = SessionLocal()
    try:
        p = Project(name="usage pipeline")
        db.add(p)
        db.commit()
        email = _own(db, p.id)
        sess = CaptureSession(project_id=p.id, source_type="extension", telemetry="present",
                              status="captured", duration_ms=4000)
        db.add(sess)
        db.commit()
        for i, t in enumerate([1000, 3000]):
            db.add(Event(session_id=sess.id, seq=i, type="click", t_ms=t, selector=f"#b{i}",
                         text=f"Button {i}", bbox_json=[i, i, 8, 8]))
        db.commit()

        run_pipeline(sess.id)
        row = db.scalar(select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == p.id))
        a = one(spans, "workflow_graph.generated", feature="workflow", action="extract_workflow",
                entity_type="workflow_graph", entity_id=row.id, email=email)
        assert a["usage.source"] == "extension" and a["usage.item_count"] == 2
        assert "session.id" not in a  # no sign-in session inside a worker
    finally:
        db.close()


def test_pipeline_missing_session_is_not_usage(spans):
    from worker.pipeline.run import run_pipeline

    assert run_pipeline("no-such-session")["skipped"]
    assert usage_spans(spans, "workflow_graph.generated") == []


# --------------------------------------------------------------------------- #
# video
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_render_records_video_rendered(spans):
    from tests.test_render import _setup
    from worker.pipeline.render import run_render

    db = SessionLocal()
    try:
        vp = _setup(db)
        email = _own(db, vp.project_id)
        job = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job)
        db.commit()
        run_render(job.id)
        a = one(spans, "video.rendered", feature="video", action="render_video",
                entity_type="render_job", entity_id=job.id, email=email)
        assert a["usage.scenes_rendered"] == 3 and a["usage.scenes_reused"] == 0
        assert a["usage.item_count"] == 3
    finally:
        db.close()


def test_render_failure_is_marked_and_reraised(spans):
    from worker.pipeline.render import run_render

    db = SessionLocal()
    try:
        job = RenderJob(video_project_id="missing-video-project", status="pending")
        db.add(job)
        db.commit()
        with pytest.raises(Exception) as exc:
            run_render(job.id)
        (s,) = usage_spans(spans, "video.rendered")
        assert s.attributes["usage.result"] == "failure"
        assert s.attributes["error.type"] == type(exc.value).__name__
        assert s.status.status_code == StatusCode.ERROR
    finally:
        db.close()


@needs_ffmpeg
def test_autoedit_records_video_auto_edited(spans):
    from tests.test_autoedit import _make_video
    from worker.pipeline.autoedit_job import run_autoedit

    db = SessionLocal()
    try:
        p = Project(name="usage ae")
        db.add(p)
        db.commit()
        email = _own(db, p.id)
        sess = CaptureSession(project_id=p.id, source_type="upload", telemetry="absent", status="ready")
        db.add(sess)
        db.commit()
        key = f"sessions/{sess.id}/raw_video.mp4"
        _make_video(store.local_path(key))
        db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=key))
        job = AutoEditJob(project_id=p.id, status="pending")
        db.add(job)
        db.commit()
        run_autoedit(job.id)
        a = one(spans, "video.auto_edited", feature="video", action="auto_edit",
                entity_type="autoedit_job", entity_id=job.id, email=email)
        assert a["usage.preset"] == "balanced"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# documentation
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_document_generated_once_and_stale_copies_ignored(spans):
    from tests.test_docgen_job import _setup
    from worker.pipeline.docgen_job import run_document_generate

    db = SessionLocal()
    try:
        p, _ = _setup(db)
        email = _own(db, p.id)
        run_document_generate(p.id, 1)
        run_document_generate(p.id, 1)  # redelivery: already ready
        run_document_generate(p.id, 99)  # stale version
        doc_id = db.scalar(select(Document.id).where(Document.project_id == p.id))
        a = one(spans, "document.generated", feature="documentation", action="generate_document",
                entity_type="document", entity_id=doc_id, email=email)
        assert a["usage.item_count"] >= 1 and a["usage.skill_used"] is False
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# media library
# --------------------------------------------------------------------------- #
def _library_image(db, user_id: str) -> str:
    a = LibraryAsset(user_id=user_id, kind="image", name="logo.png", ext="png", storage_key="",
                     status="processing")
    db.add(a)
    db.flush()
    a.storage_key = f"library/{a.id}/original.png"
    out = store.local_path(a.storage_key)
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (80, 80), (255, 255, 255))
    im.paste((30, 143, 142), (20, 20, 60, 60))
    im.save(out)
    db.commit()
    return a.id


@needs_ffmpeg
def test_background_removed(spans):
    from worker.pipeline.library import process_asset, remove_background

    db = SessionLocal()
    try:
        u = _owner(db)
        aid = _library_image(db, u.id)
        process_asset(aid)
        remove_background(aid)
        a = one(spans, "library_asset.background_removed", feature="media_library",
                action="remove_background", entity_type="library_asset", entity_id=aid,
                email=u.email)
        assert a.get("usage.method")
    finally:
        db.close()


def test_import_with_missing_source_is_a_failure(spans):
    from worker.pipeline.library import import_recording

    db = SessionLocal()
    try:
        u = _owner(db)
        a = LibraryAsset(user_id=u.id, kind="video", name="rec", ext="mp4", source="recording",
                         storage_key=f"sessions/{uuid.uuid4().hex}/gone.mp4", status="processing")
        db.add(a)
        db.commit()
        import_recording(a.id)
        f = one(spans, "library_asset.imported", feature="media_library",
                action="import_recording", entity_type="library_asset", entity_id=a.id,
                email=u.email, result="failure")
        assert f["usage.error.code"] == "SOURCE_MISSING"
        assert f["usage.error.category"] == "user" and f["usage.error.handled"] is True
        assert f["usage.error.stage"] == "load"
    finally:
        db.close()


@needs_ffmpeg
def test_import_recording_succeeds(spans):
    from tests.test_autoedit import _make_video
    from worker.pipeline.library import import_recording

    db = SessionLocal()
    try:
        u = _owner(db)
        key = f"sessions/{uuid.uuid4().hex}/raw_video.mp4"
        _make_video(store.local_path(key))
        a = LibraryAsset(user_id=u.id, kind="video", name="rec", ext="mp4", source="recording",
                         storage_key=key, status="processing")
        db.add(a)
        db.commit()
        import_recording(a.id)
        one(spans, "library_asset.imported", feature="media_library", action="import_recording",
            entity_type="library_asset", entity_id=a.id, email=u.email)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# narration from the whole recording
# --------------------------------------------------------------------------- #
def _narration_job(db) -> tuple[str, str, str]:
    from app.models import Job

    p = Project(name="narration")
    db.add(p)
    db.commit()
    email = _own(db, p.id)
    sess = CaptureSession(project_id=p.id, source_type="upload", telemetry="absent",
                          status="ready", duration_ms=20_000)
    db.add(sess)
    db.commit()
    job = Job(session_id=sess.id, stage="script", version=0, status="pending")
    db.add(job)
    db.commit()
    return sess.id, job.id, email


@pytest.fixture
def vj(monkeypatch):
    from worker.pipeline import videoscript_job

    monkeypatch.setattr(videoscript_job, "has_llm", lambda: True)
    monkeypatch.setattr(videoscript_job, "enqueue_understanding", lambda sid: None)
    return videoscript_job


def test_narration_generated(spans, vj, monkeypatch):
    from app.videoscript import TimedLine

    lines = [TimedLine(0.0, "Open the dashboard."), TimedLine(8.0, "Click Create.")]
    monkeypatch.setattr(vj, "_write_script", lambda *a, **k: (lines, None))
    db = SessionLocal()
    try:
        sid, job_id, email = _narration_job(db)
    finally:
        db.close()
    assert vj.run_video_script(sid, job_id, "a brief", "free", "be upbeat") == {"lines": 2}
    a = one(spans, "narration.generated", feature="ai_assist", action="generate_narration",
            entity_type="capture_session", entity_id=sid, email=email)
    assert a["usage.item_count"] == 2 and a["usage.mode"] == "free"
    assert a["usage.custom_instruction"] is True
    assert "a brief" not in str(a) and "upbeat" not in str(a)  # never the prompt text

    spans.clear()  # a redelivered copy of a finished job builds nothing
    vj.run_video_script(sid, job_id, "a brief")
    assert usage_spans(spans, "narration.generated") == []


@pytest.mark.parametrize(
    ("setup", "code", "category", "stage"),
    [
        ("no_key", "AI_NOT_CONFIGURED", "system", "validate"),
        ("empty", "AI_EMPTY_RESULT", "external", "generate"),
        ("crash", "UNEXPECTED_ERROR", "system", "generate"),
    ],
)
def test_narration_failure_says_why(spans, vj, monkeypatch, setup, code, category, stage):
    if setup == "no_key":
        monkeypatch.setattr(vj, "has_llm", lambda: False)
    elif setup == "empty":
        monkeypatch.setattr(vj, "_write_script", lambda *a, **k: ([], None))
    else:
        def boom(*_a, **_k):
            raise KeyError("frame 12")

        monkeypatch.setattr(vj, "_write_script", boom)
    db = SessionLocal()
    try:
        sid, job_id, email = _narration_job(db)
    finally:
        db.close()
    assert "error" in vj.run_video_script(sid, job_id, "brief")  # recorded on the row, not raised
    (s,) = usage_spans(spans, "narration.generated")
    a = s.attributes
    assert a["usage.result"] == "failure" and s.status.status_code == StatusCode.ERROR
    assert (a["usage.error.code"], a["usage.error.category"], a["usage.error.stage"]) == (
        code, category, stage)
    assert a["usage.error.target"] == "capture_session" and a["user.id"] == email
    assert [e.name for e in s.events] == ["exception"]
    assert "frame 12" not in str(dict(a)) + str([dict(e.attributes) for e in s.events])
