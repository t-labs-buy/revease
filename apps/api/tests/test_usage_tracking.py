"""Usage Tracker spans: exactly one usage span per catalogued API action, with
the right feature/action/event/entity/result and WHO attributes; failures are
marked and re-raised; plain reads and no-op repeats produce no usage span.

Spans go to an in-memory exporter (no network). Worker-side events are covered
in apps/workers/tests/test_usage_tracking.py."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

import app.rewrite
from app import usage_tracking
from app.auth import decode_access_token
from app.db import SessionLocal
from app.models import RenderJob, VideoProject, WorkflowGraphRow
from app.routers import auto_record as ar_router
from app.routers import documents as documents_router
from app.routers import library as library_router
from app.routers import rewrite as rewrite_router
from app.routers import video as video_router
from tests.helpers import client, other_client
from tests.test_documents import _project as _doc_project
from tests.test_documents import _ready_doc

OWNER = "owner@example.com"
GRAPH = {
    "workflow_id": "wf_u", "version": 1, "title": "Usage Demo",
    "steps": [{"id": "s1", "action": "click", "target": "Go", "narration": "Go."}],
    "edges": [],
}


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    usage_tracking.set_provider(provider)
    yield exporter
    usage_tracking.set_provider(None)


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    """Routes enqueue by name; none of these tests needs a broker."""
    for mod, names in (
        (ar_router, ["enqueue_understanding"]),
        (documents_router, ["enqueue_document_generate", "enqueue_document_snapshot"]),
        (library_router, ["enqueue_library_process", "enqueue_library_remove_bg",
                          "enqueue_library_import"]),
        (video_router, ["enqueue_render", "enqueue_voice_track"]),
    ):
        for n in names:
            monkeypatch.setattr(mod, n, lambda *a, **k: None)
    import app.routers.sessions as sessions_router

    monkeypatch.setattr(sessions_router, "enqueue_understanding", lambda *a, **k: None)


def usage_spans(exporter, event: str | None = None) -> list:
    out = [s for s in exporter.get_finished_spans() if "usage.feature" in (s.attributes or {})]
    return [s for s in out if event is None or s.attributes["usage.event.name"] == event]


def one(exporter, event: str, *, feature: str, action: str, entity_type: str,
        entity_id: str | None = None, result: str = "success") -> dict:
    found = usage_spans(exporter, event)
    assert len(found) == 1, [s.attributes for s in usage_spans(exporter)]
    s = found[0]
    a = dict(s.attributes)
    assert s.kind == SpanKind.INTERNAL
    assert a["usage.feature"] == feature
    assert a["usage.action"] == action
    assert a["usage.entity.type"] == entity_type
    assert a["usage.result"] == result
    if entity_id is not None:
        assert a["usage.entity.id"] == entity_id
    else:
        assert a.get("usage.entity.id")
    assert a["user.id"] == OWNER
    assert a.get("session.id"), "API events carry the sign-in session id"
    return a


def _project(name: str = "usage") -> str:
    return client.post("/projects", json={"name": name}).json()["id"]


def _with_graph(pid: str) -> None:
    db = SessionLocal()
    db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json=GRAPH))
    db.commit()
    db.close()


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
def test_session_id_is_the_token_sid(spans):
    token = client.headers["Authorization"].split(" ", 1)[1]
    _, _, sid = decode_access_token(token)
    assert sid
    pid = _project()
    a = one(spans, "project.created", feature="project", action="create_project",
            entity_type="project", entity_id=pid)
    assert a["session.id"] == sid


# --------------------------------------------------------------------------- #
# project
# --------------------------------------------------------------------------- #
def test_project_created_and_deleted(spans):
    pid = _project()
    one(spans, "project.created", feature="project", action="create_project",
        entity_type="project", entity_id=pid)
    assert client.delete(f"/projects/{pid}").status_code == 204
    one(spans, "project.deleted", feature="project", action="delete_project",
        entity_type="project", entity_id=pid)


def test_collaborator_added_once(spans):
    pid = _project()
    for _ in range(2):  # idempotent invite: the repeat adds nobody
        assert client.post(f"/projects/{pid}/collaborators",
                           json={"email": "other@example.com"}).status_code == 201
    one(spans, "collaborator.added", feature="project", action="add_collaborator",
        entity_type="project", entity_id=pid)


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #
def test_capture_completed_once_and_reprocessed(spans):
    pid = _project()
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "recorder"}).json()["id"]
    for _ in range(2):  # a re-sent complete is not a second capture
        assert client.post(f"/sessions/{sid}/complete", json={"duration_ms": 1000}).status_code == 200
    a = one(spans, "capture.completed", feature="capture", action="complete_capture",
            entity_type="capture_session", entity_id=sid)
    assert a["usage.source"] == "recorder" and a["usage.has_telemetry"] is False

    assert client.post(f"/sessions/{sid}/reprocess").status_code == 200
    one(spans, "capture.reprocessed", feature="capture", action="reprocess_capture",
        entity_type="capture_session", entity_id=sid)


def test_script_imported_and_refused_while_running(spans):
    from app.models import Job

    pid = _project()
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "recorder"}).json()["id"]
    assert client.put(f"/sessions/{sid}/script", json={"script": "Line one.\n\nLine two."}).status_code == 200
    a = one(spans, "script.imported", feature="capture", action="import_script",
            entity_type="capture_session", entity_id=sid)
    assert a["usage.item_count"] == 2

    spans.clear()
    assert client.put(f"/sessions/{sid}/script", json={"script": "  "}).status_code == 200
    assert usage_spans(spans) == []  # clearing the script imports nothing

    db = SessionLocal()
    db.add(Job(session_id=sid, stage="extract", version=1, status="running"))
    db.commit()
    db.close()
    assert client.put(f"/sessions/{sid}/script", json={"script": "x"}).status_code == 409
    s = usage_spans(spans, "script.imported")[0]
    assert s.attributes["usage.result"] == "failure"
    assert s.attributes["usage.error.code"] == "RUN_IN_PROGRESS"
    assert s.attributes["usage.error.stage"] == "validate"


# --------------------------------------------------------------------------- #
# auto record
# --------------------------------------------------------------------------- #
def _run(pid: str) -> str:
    r = client.post("/auto-record/runs", json={"project_id": pid, "coverage_plan": "- a\n- b"})
    assert r.status_code == 201
    return r.json()["run_id"]


def test_autorecord_started_and_finished(spans):
    run_id = _run(_project())
    a = one(spans, "autorecord_run.started", feature="auto_record", action="start_run",
            entity_type="autorecord_run", entity_id=run_id)
    assert a["usage.item_count"] == 2
    assert client.post(f"/auto-record/runs/{run_id}/complete", json={}).status_code == 200
    one(spans, "autorecord_run.finished", feature="auto_record", action="finish_run",
        entity_type="autorecord_run", entity_id=run_id)


def test_autorecord_abort_is_cancelled_and_counted_once(spans):
    run_id = _run(_project())
    for _ in range(2):  # the second abort finds the run already terminal
        assert client.post(f"/auto-record/runs/{run_id}/abort").status_code == 200
    one(spans, "autorecord_run.finished", feature="auto_record", action="finish_run",
        entity_type="autorecord_run", entity_id=run_id, result="cancelled")


def test_autorecord_reported_failure(spans):
    run_id = _run(_project())
    client.post(f"/auto-record/runs/{run_id}/complete", json={"status": "failed"})
    s = usage_spans(spans, "autorecord_run.finished")[0]
    assert s.attributes["usage.result"] == "failure"
    assert s.status.status_code == StatusCode.ERROR
    assert s.attributes["usage.error.code"] == "AUTORECORD_FAILED"
    assert s.attributes["usage.error.category"] == "external"
    assert s.attributes["usage.error.stage"] == "execute"


# --------------------------------------------------------------------------- #
# video + AI assist
# --------------------------------------------------------------------------- #
def test_voice_track_generated(spans):
    pid = _project()
    _with_graph(pid)
    r = client.post(f"/projects/{pid}/voice-track", json={"voice_id": "af_heart", "speed": 1.0})
    assert r.status_code == 200
    a = one(spans, "voice_track.generated", feature="video", action="generate_voice_track",
            entity_type="project", entity_id=pid)
    assert a["usage.voice"] == "af_heart"


def test_ai_assist_events(spans, monkeypatch):
    monkeypatch.setattr(rewrite_router, "rewrite_lines", lambda lines, instr: [x.upper() for x in lines])
    monkeypatch.setattr(rewrite_router, "generate_script", lambda scenes, title, instr: ["a", "b"])
    monkeypatch.setattr(rewrite_router, "suggest_zooms_with_source",
                        lambda scenes: ([{"scene": 0}], "anthropic:some-model"))
    pid = _project()
    assert client.post(f"/projects/{pid}/rewrite", json={"lines": ["x", "y"]}).status_code == 200
    a = one(spans, "script.rewritten", feature="ai_assist", action="rewrite_script",
            entity_type="project", entity_id=pid)
    assert a["usage.item_count"] == 2 and a["usage.custom_instruction"] is False

    assert client.post(f"/projects/{pid}/generate-script",
                       json={"scenes": [{}, {}], "instruction": "short"}).status_code == 200
    a = one(spans, "script.generated", feature="ai_assist", action="generate_script",
            entity_type="project", entity_id=pid)
    assert a["usage.custom_instruction"] is True

    assert client.post(f"/projects/{pid}/suggest-zooms", json={"scenes": [{}]}).status_code == 200
    a = one(spans, "zooms.suggested", feature="ai_assist", action="suggest_zooms",
            entity_type="project", entity_id=pid)
    assert a["usage.engine"] == "anthropic"  # provider only, never the model string


def test_ai_failure_is_marked_and_still_raises(spans, monkeypatch):
    def boom(*_a):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(rewrite_router, "rewrite_lines", boom)
    pid = _project()
    r = client.post(f"/projects/{pid}/rewrite", json={"lines": ["x"]})
    assert r.status_code == 502  # the route's own error handling is untouched
    s = usage_spans(spans, "script.rewritten")[0]
    assert s.attributes["usage.result"] == "failure"
    assert s.attributes["error.type"] == "HTTPException"
    assert s.status.status_code == StatusCode.ERROR
    a = s.attributes
    assert a["usage.error.code"] == "AI_PROVIDER_FAILED"
    assert a["usage.error.category"] == "external" and a["usage.error.handled"] is True
    assert a["usage.error.stage"] == "generate" and a["usage.error.target"] == "project"
    assert "upstream down" not in str(a)  # the message is the table's, not the exception's
    assert [e.name for e in s.events] == ["exception"]


def test_empty_ai_requests_are_not_usage(spans):
    pid = _project()
    client.post(f"/projects/{pid}/rewrite", json={"lines": []})
    client.post(f"/projects/{pid}/suggest-zooms", json={"scenes": []})
    assert usage_spans(spans, "script.rewritten") == []
    assert usage_spans(spans, "zooms.suggested") == []


# --------------------------------------------------------------------------- #
# documentation
# --------------------------------------------------------------------------- #
def test_document_export_and_snapshot_regrab(spans):
    pid, sid = _doc_project()
    _ready_doc(pid, sid)
    doc_id = client.get(f"/projects/{pid}/document").json()["document_id"]

    assert client.get(f"/projects/{pid}/document/export", params={"format": "pdf"}).status_code == 200
    a = one(spans, "document.exported", feature="documentation", action="export_document",
            entity_type="document", entity_id=doc_id)
    assert a["usage.format"] == "pdf"

    assert client.post(f"/projects/{pid}/document/steps/s2/snapshot", json={"t": 1.0}).status_code == 202
    one(spans, "snapshot.regrabbed", feature="documentation", action="regrab_snapshot",
        entity_type="document", entity_id=doc_id)


# --------------------------------------------------------------------------- #
# sharing
# --------------------------------------------------------------------------- #
def test_share_created_once_and_revoked_without_token(spans):
    pid = _project()
    _with_graph(pid)
    db = SessionLocal()
    vp = VideoProject(project_id=pid, graph_version=1, edit_spec_json={})
    db.add(vp)
    db.commit()
    db.add(RenderJob(video_project_id=vp.id, status="done", output_key="renders/u/final.mp4"))
    db.commit()
    db.close()

    token = client.post(f"/projects/{pid}/share", json={"kind": "video"}).json()["token"]
    client.post(f"/projects/{pid}/share", json={"kind": "video"})  # reuses the same link
    a = one(spans, "share.created", feature="sharing", action="create_share", entity_type="share")
    assert a["usage.share_kind"] == "video"
    assert token not in a.values(), "the public token must never leave as telemetry"

    assert client.delete(f"/shares/{token}").status_code == 200
    a2 = one(spans, "share.revoked", feature="sharing", action="revoke_share",
             entity_type="share", entity_id=a["usage.entity.id"])
    assert token not in a2.values()


# --------------------------------------------------------------------------- #
# media library
# --------------------------------------------------------------------------- #
def test_library_upload_counted_once(spans):
    data = b"\x89PNG fake"
    asset = client.post("/library", json={"name": "logo.png", "ext": "png", "size": len(data)}).json()
    assert client.put(asset["put_url"], content=data).status_code == 204
    for _ in range(2):
        assert client.post(f"/library/{asset['id']}/uploaded").status_code == 200
    a = one(spans, "library_asset.uploaded", feature="media_library", action="upload_asset",
            entity_type="library_asset", entity_id=asset["id"])
    assert a["usage.asset_kind"] == "image"


# --------------------------------------------------------------------------- #
# skills, knowledge base, branding
# --------------------------------------------------------------------------- #
def test_skill_kb_and_brand_creation(spans, monkeypatch):
    monkeypatch.setattr(app.rewrite, "generate_skill", lambda prompt, target: {
        "name": "Short", "description": "d", "target": "doc", "settings": {}})
    gen = client.post("/skills/generate", json={"prompt": "make it short"}).json()
    a = one(spans, "skill.generated", feature="skills", action="generate_skill",
            entity_type="skill", entity_id=gen["id"])
    assert a["usage.skill_target"] == "doc"

    made = client.post("/skills", json={"name": "Mine"}).json()
    one(spans, "skill.created", feature="skills", action="create_skill",
        entity_type="skill", entity_id=made["id"])

    art = client.post("/kb", json={"title": "How to"}).json()
    one(spans, "kb_article.created", feature="knowledge_base", action="create_article",
        entity_type="kb_article", entity_id=art["id"])

    pkg = client.post("/packages", json={"name": "Brand"}).json()
    one(spans, "brand_package.created", feature="branding", action="create_brand_package",
        entity_type="brand_package", entity_id=pkg["id"])


# --------------------------------------------------------------------------- #
# what must NOT be usage
# --------------------------------------------------------------------------- #
def test_plain_reads_produce_no_usage_span(spans):
    pid = _project()
    spans.clear()
    client.get("/projects")
    client.get(f"/projects/{pid}")
    client.get("/skills")
    client.get("/library")
    assert usage_spans(spans) == []


def test_unowned_row_is_a_failure_not_a_leak(spans):
    pid = _project()
    spans.clear()
    assert other_client.delete(f"/projects/{pid}").status_code == 404
    s = usage_spans(spans, "project.deleted")[0]
    assert s.attributes["usage.result"] == "failure"
    assert s.attributes["user.id"] == "other@example.com"
    assert s.attributes["usage.error.code"] == "NOT_FOUND"
    assert s.attributes["usage.error.category"] == "user"
    assert s.attributes["usage.error.handled"] is True
    assert s.attributes["usage.error.stage"] == "validate"


# --------------------------------------------------------------------------- #
# the helper itself
# --------------------------------------------------------------------------- #
def test_helper_rethrows_and_marks_failure(spans):
    with pytest.raises(ValueError):
        with usage_tracking.track("f", "a", "thing.done", "thing", entity_id="1"):
            raise ValueError("secret detail")
    (s,) = usage_spans(spans)
    assert s.attributes["usage.result"] == "failure"
    assert s.attributes["error.type"] == "ValueError"
    assert s.status.status_code == StatusCode.ERROR
    a = s.attributes
    assert a["usage.error.code"] == "UNEXPECTED_ERROR"
    assert a["usage.error.category"] == "system" and a["usage.error.handled"] is False
    assert a["usage.error.stage"] == "execute" and a["usage.error.target"] == "thing"
    assert a["usage.error.message"] == usage_tracking.ERRORS["UNEXPECTED_ERROR"][2]
    (ev,) = s.events  # recorded, but without the message (it can carry user content)
    assert ev.name == "exception" and ev.attributes["exception.type"] == "ValueError"
    assert "secret detail" not in str(a) and "secret detail" not in str(ev.attributes)


def test_named_code_before_raise_wins(spans):
    with pytest.raises(RuntimeError):
        with usage_tracking.track("f", "a", "thing.generated", "thing") as u:
            u.failed("AI_EMPTY_RESULT", target="narration")
            raise RuntimeError("nothing came back")
    (s,) = usage_spans(spans)
    a = s.attributes
    assert a["usage.error.code"] == "AI_EMPTY_RESULT" and a["usage.error.category"] == "external"
    assert a["usage.error.stage"] == "generate" and a["usage.error.target"] == "narration"


def test_handled_failure_without_raise_is_recorded(spans):
    with usage_tracking.track("f", "a", "thing.done", "thing", entity_id="1") as u:
        try:
            raise OSError("disk")
        except OSError as e:
            u.failed(exc=e, stage="load")
    (s,) = usage_spans(spans)
    assert s.attributes["usage.result"] == "failure" and s.status.status_code == StatusCode.ERROR
    assert s.attributes["usage.error.code"] == "UNEXPECTED_ERROR"
    assert s.attributes["usage.error.stage"] == "load"
    assert s.attributes["error.type"] == "OSError" and len(s.events) == 1


def test_every_error_code_is_well_formed():
    for code, (category, handled, message) in usage_tracking.ERRORS.items():
        assert code.isupper() and category in ("user", "system", "external")
        assert isinstance(handled, bool) and message.endswith(".")


def test_unsampled_parent_starts_a_new_root(spans):
    from opentelemetry import trace
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    parent = SpanContext(trace_id=0xABC, span_id=0xDEF, is_remote=True,
                         trace_flags=TraceFlags(TraceFlags.DEFAULT))
    with trace.use_span(NonRecordingSpan(parent)):
        with usage_tracking.track("f", "a", "thing.done", "thing", entity_id="1"):
            pass
    (s,) = usage_spans(spans)
    assert s.parent is None and s.context.trace_id != 0xABC


def test_disabled_tracking_is_a_no_op():
    usage_tracking.set_provider(False)
    try:
        with usage_tracking.track("f", "a", "thing.done", "thing") as u:
            u.entity("1").set(x=1)
        assert _project("still works")
    finally:
        usage_tracking.set_provider(None)
