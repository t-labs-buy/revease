"""Document model upgrade, the three renderers, and the document routes (the
worker is mocked: routes only enqueue by name)."""

from __future__ import annotations

import io
import zipfile

import pytest
from pydantic import ValidationError

from app import docgen
from app.db import SessionLocal
from app.docgen import DOCX_MEDIA_TYPE, build_document_v2, render_docx, render_markdown, render_pdf, upgrade_doc
from app.models import CaptureSession, Document, MediaAsset, Skill, WorkflowGraphRow
from app.routers import documents as documents_router
from app.schemas import DocV2
from app.storage import store
from tests.helpers import client

GRAPH = {
    "workflow_id": "wf_d",
    "version": 1,
    "title": "Create an API key",
    "steps": [
        {"id": "s1", "action": "click", "target": "Settings → API Keys", "intent": "Open the API Keys page",
         "narration": "Open the API Keys page.", "screenshot": None, "t_start": 0.0, "t_end": 2.0},
        {"id": "s2", "action": "click", "target": "Create key", "intent": "Create a key",
         "narration": "Click Create key.", "screenshot": None, "t_start": 2.0, "t_end": 4.0},
    ],
    "edges": [{"from": "s1", "to": "s2", "condition": None}],
}

V1_DOC = {
    "title": "Old doc",
    "summary": "A step-by-step guide with 2 steps.",
    "graph_version": 1,
    "steps": [
        {"n": 1, "title": "Click Settings", "body": "Open it.", "screenshot": "sessions/x/frames/f1.jpg"},
        {"n": 2, "title": "Click Create key", "body": "Click it.", "screenshot": None},
    ],
}


def _jpeg(w: int = 64, h: int = 32) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 143, 142)).save(buf, format="JPEG")
    return buf.getvalue()


def _doc_with_images(sid: str = "sess1") -> dict:
    keys = [f"sessions/{sid}/docshots/s1_100.jpg", f"sessions/{sid}/docshots/s2_2100.jpg"]
    # different sizes: python-docx dedupes byte-identical images into one part
    for i, k in enumerate(keys):
        store.write(k, _jpeg(64 + 16 * i, 32))
    return DocV2.model_validate({
        "title": "Créer une clé → 日本語",
        "overview": "Make a key in **Settings**.",
        "prerequisites": ["An admin account"],
        "steps": [
            {"id": "s1", "title": "Open the API Keys page", "body": "Click **Settings**, then **API Keys**.",
             "tip": "The menu may be collapsed.", "snapshot": {"key": keys[0], "raw_key": keys[0], "t": 0.1},
             "source": {"graph_step_id": "s1", "t_start": 0, "t_end": 2}},
            {"id": "s2", "title": "Create the key", "body": "Type `production` and click **Create key**.",
             "snapshot": {"key": keys[1], "t": 2.1}, "source": {"graph_step_id": "s2"}},
        ],
        "tips": ["Copy the key once."],
        "meta": {"writer": "llm"},
    }).model_dump()


# ---- model ----


def test_upgrade_doc_v1_to_v2_and_idempotent():
    d = upgrade_doc(V1_DOC, GRAPH)
    assert d["version"] == 2 and d["meta"]["writer"] == "legacy"
    assert d["overview"] == V1_DOC["summary"]
    assert d["steps"][0]["id"] == "legacy_1" and d["steps"][0]["source"]["graph_step_id"] == "s1"
    assert d["steps"][0]["snapshot"]["key"] == "sessions/x/frames/f1.jpg"
    assert d["steps"][1]["snapshot"] is None
    assert upgrade_doc(d) == d
    # without an aligned graph the step id is unknown
    assert upgrade_doc(V1_DOC)["steps"][0]["source"]["graph_step_id"] is None


def test_docv2_rejects_duplicate_ids_and_cleans_text():
    with pytest.raises(ValidationError):
        DocV2.model_validate({"title": "t", "steps": [{"id": "a"}, {"id": "a"}]})
    d = DocV2.model_validate({"title": "  T\x00itle  ", "overview": "a\n\n\n\nb", "steps": [{"id": "a", "title": "x\x07y"}],
                              "prerequisites": ["", "  keep  ", 3]})
    assert d.title == "Title" and d.overview == "a\n\nb" and d.steps[0].title == "xy"
    assert d.prerequisites == ["keep"]
    assert DocV2.model_validate({"title": ""}).title == "Untitled document"


def test_build_document_v2_from_graph_uses_keyframes():
    g = {**GRAPH, "steps": [{**GRAPH["steps"][0], "screenshot": "sessions/x/frames/f1.jpg", "bbox": [64, 36, 128, 72]}]}
    d = build_document_v2(g, viewport={"w": 1280, "h": 720})
    assert d["title"] == "Create an API key" and d["steps"][0]["id"] == "s1"
    assert d["steps"][0]["snapshot"]["bbox_norm"] == [0.05, 0.05, 0.1, 0.1]


# ---- renderers ----


def test_markdown_render_sections():
    md = render_markdown(_doc_with_images(), media_base="http://x")
    assert md.startswith("# Créer une clé → 日本語")
    assert "## Prerequisites\n\n- An admin account" in md
    assert "## 1. Open the API Keys page" in md and "> **Tip:** The menu may be collapsed." in md
    assert "![Step 1](http://x/media/sessions/sess1/docshots/s1_100.jpg)" in md
    assert "## Tips & troubleshooting\n\n- Copy the key once." in md
    assert "## 1. Click Settings" in render_markdown(V1_DOC)  # legacy still renders


def test_pdf_render_embeds_unicode_font():
    assert docgen.resolve_pdf_font() is not None  # fonts ship with the package
    pdf = render_pdf(_doc_with_images())
    assert pdf[:4] == b"%PDF" and len(pdf) > 500
    assert b"DejaVuSans" in pdf


def test_pdf_render_without_bundled_font_degrades(monkeypatch):
    monkeypatch.setattr(docgen, "resolve_pdf_font", lambda: None)
    assert render_pdf(_doc_with_images())[:4] == b"%PDF"


def test_docx_render_is_valid_with_images_and_inline_markup():
    b = render_docx(_doc_with_images())
    z = zipfile.ZipFile(io.BytesIO(b))
    assert z.testzip() is None
    xml = z.read("word/document.xml").decode()
    assert xml.count('w:val="Heading2"') == 2
    assert len([n for n in z.namelist() if n.startswith("word/media/")]) == 2
    assert "Créer une clé" in xml and "<w:b/>" in xml and "**" not in xml
    assert "production" in xml and "`" not in xml


# ---- routes ----


def _project(with_video: bool = True, graph: dict | None = None) -> tuple[str, str]:
    pid = client.post("/projects", json={"name": "doc proj"}).json()["id"]
    db = SessionLocal()
    sess = CaptureSession(project_id=pid, source_type="upload", telemetry="absent", status="ready")
    db.add(sess)
    db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json=graph or GRAPH))
    db.commit()
    db.refresh(sess)
    if with_video:
        db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=f"sessions/{sess.id}/raw_video.mp4"))
        db.commit()
    sid = sess.id
    db.close()
    return pid, sid


def test_get_without_document_is_none_and_404_without_graph():
    pid, _ = _project()
    r = client.get(f"/projects/{pid}/document")
    assert r.status_code == 200 and r.json()["status"] == "none" and r.json()["doc"] is None
    assert r.json()["latest_graph_version"] == 1
    empty = client.post("/projects", json={"name": "empty"}).json()["id"]
    assert client.get(f"/projects/{empty}/document").status_code == 404


def test_generate_enqueues_by_name_and_guards(monkeypatch):
    pid, _ = _project()
    calls: list[tuple] = []
    monkeypatch.setattr(documents_router, "enqueue_document_generate", lambda *a: calls.append(a))

    r = client.post(f"/projects/{pid}/document/generate", json={"instruction": "short"})
    assert r.status_code == 202
    assert r.json()["status"] == "queued" and r.json()["doc_version"] == 1 and r.json()["doc"] is None
    assert calls == [(pid, 1, None, "short")]

    # already queued -> no second enqueue
    assert client.post(f"/projects/{pid}/document/generate", json={}).status_code == 202
    assert len(calls) == 1

    # a queued doc does not count as a document
    proj = client.get(f"/projects/{pid}").json()
    assert proj["has_document"] is False and proj["document_status"] == "queued"

    # editing / re-grabbing while generating is refused
    doc = DocV2(title="x").model_dump()
    assert client.patch(f"/projects/{pid}/document", json={"doc": doc}).status_code == 409
    assert client.post(f"/projects/{pid}/document/steps/s1/snapshot", json={"t": 1.0}).status_code == 409


def test_generate_requires_video_and_doc_skill(monkeypatch):
    monkeypatch.setattr(documents_router, "enqueue_document_generate", lambda *a: None)
    pid, _ = _project(with_video=False)
    assert client.post(f"/projects/{pid}/document/generate", json={}).status_code == 409

    pid, _ = _project()
    db = SessionLocal()
    from app.models import User

    uid = db.scalar(__import__("sqlalchemy").select(User.id).where(User.email == "owner@example.com"))
    video_skill = Skill(user_id=uid, name="v", target="video", settings_json={})
    doc_skill = Skill(user_id=uid, name="d", target="doc", settings_json={})
    db.add_all([video_skill, doc_skill])
    db.commit()
    vid, did = video_skill.id, doc_skill.id
    db.close()
    assert client.post(f"/projects/{pid}/document/generate", json={"skill_id": vid}).status_code == 400
    assert client.post(f"/projects/{pid}/document/generate", json={"skill_id": did}).status_code == 202
    assert client.post(f"/projects/{pid}/document/generate", json={"skill_id": "nope"}).status_code == 404


def _ready_doc(pid: str, sid: str) -> None:
    db = SessionLocal()
    row = db.scalar(__import__("sqlalchemy").select(Document).where(Document.project_id == pid))
    doc = _doc_with_images(sid)
    if row is None:
        db.add(Document(project_id=pid, graph_version=1, doc_json=doc, status="ready", doc_version=1))
    else:
        row.doc_json, row.status = doc, "ready"
    db.commit()
    db.close()


def test_patch_reorders_deletes_and_validates_keys():
    pid, sid = _project()
    _ready_doc(pid, sid)
    r = client.get(f"/projects/{pid}/document")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    doc = r.json()["doc"]
    assert [s["id"] for s in doc["steps"]] == ["s1", "s2"]

    # reorder + delete + edit + a user-added step
    edited = {**doc, "title": "Edited title", "steps": [
        {**doc["steps"][1], "body": "Changed body."},
        {"id": "u_abc12345", "title": "Verify the key", "body": "Check the list.", "snapshot": None,
         "source": {"graph_step_id": None}},
    ]}
    r = client.patch(f"/projects/{pid}/document", json={"doc": edited})
    assert r.status_code == 200, r.text
    got = r.json()["doc"]
    assert got["title"] == "Edited title" and [s["id"] for s in got["steps"]] == ["s2", "u_abc12345"]
    assert got["steps"][0]["body"] == "Changed body."
    assert got["meta"]["writer"] == "llm" and got["meta"]["edited_at"]
    assert client.get(f"/projects/{pid}/document").json()["doc"]["title"] == "Edited title"

    foreign = {**doc, "steps": [{**doc["steps"][0], "snapshot": {"key": "sessions/other/docshots/x.jpg"}}]}
    assert client.patch(f"/projects/{pid}/document", json={"doc": foreign}).status_code == 422
    dupe = {**doc, "steps": [doc["steps"][0], doc["steps"][0]]}
    assert client.patch(f"/projects/{pid}/document", json={"doc": dupe}).status_code == 422


def test_snapshot_regrab_marks_pending_and_enqueues(monkeypatch):
    pid, sid = _project()
    _ready_doc(pid, sid)
    calls: list[tuple] = []
    monkeypatch.setattr(documents_router, "enqueue_document_snapshot", lambda *a: calls.append(a))
    r = client.post(f"/projects/{pid}/document/steps/s2/snapshot", json={"t": 3.25})
    assert r.status_code == 202
    step = next(s for s in r.json()["doc"]["steps"] if s["id"] == "s2")
    assert step["snapshot"]["pending"] is True and step["snapshot"]["key"].endswith("s2_2100.jpg")
    assert calls == [(pid, "s2", 3.25)]
    assert client.post(f"/projects/{pid}/document/steps/nope/snapshot", json={"t": 1}).status_code == 404
    assert client.post(f"/projects/{pid}/document/steps/s1/snapshot", json={"t": -1}).status_code == 422


def test_exports_all_formats_and_legacy_row_upgrades():
    pid, sid = _project()
    db = SessionLocal()
    db.add(Document(project_id=pid, graph_version=1, doc_json=V1_DOC))  # legacy row: status defaults to ready
    db.commit()
    db.close()

    r = client.get(f"/projects/{pid}/document")
    assert r.status_code == 200 and r.json()["doc"]["version"] == 2 and r.json()["status"] == "ready"
    assert r.json()["doc"]["steps"][0]["source"]["graph_step_id"] == "s1"
    assert client.get(f"/projects/{pid}").json()["has_document"] is True

    md = client.get(f"/projects/{pid}/document/export", params={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.content.startswith(b"# Old doc")
    pdf = client.get(f"/projects/{pid}/document/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    docx = client.get(f"/projects/{pid}/document/export", params={"format": "docx"})
    assert docx.status_code == 200 and docx.headers["content-type"] == DOCX_MEDIA_TYPE
    assert docx.content[:2] == b"PK" and 'filename="old-doc.docx"' in docx.headers["content-disposition"]
    assert client.get(f"/projects/{pid}/document/export", params={"format": "txt"}).status_code == 422


def test_stale_flag_after_reprocessing():
    pid, sid = _project()
    _ready_doc(pid, sid)
    db = SessionLocal()
    db.add(WorkflowGraphRow(project_id=pid, version=2, graph_json={**GRAPH, "version": 2}))
    db.commit()
    db.close()
    r = client.get(f"/projects/{pid}/document").json()
    assert r["stale"] is True and r["graph_version"] == 1 and r["latest_graph_version"] == 2


def test_dbcopy_handles_a_source_missing_new_columns(tmp_path):
    """Production SQLite predates columns added later; the copy must still work."""
    import sqlite3

    from sqlalchemy import create_engine, text

    from app.dbcopy import copy

    src = tmp_path / "old.sqlite3"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, user_id TEXT, name TEXT NOT NULL, favorite INTEGER, created_at DATETIME)")
    con.execute("INSERT INTO projects VALUES ('p1', NULL, 'Old project', 0, '2026-01-01 00:00:00')")
    con.commit()
    con.close()
    counts = copy(f"sqlite:///{src}", f"sqlite:///{tmp_path / 'new.sqlite3'}")
    assert counts["projects"] == 1 and counts["capture_sessions"] == 0
    with create_engine(f"sqlite:///{tmp_path / 'new.sqlite3'}").connect() as c:
        assert c.execute(text("select name from projects")).scalar() == "Old project"
