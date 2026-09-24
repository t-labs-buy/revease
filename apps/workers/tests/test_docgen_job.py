"""End-to-end documentation generation against a synthetic recording. Needs
ffmpeg for the frame grabs (skipped without it); the writer runs its offline
fallback because conftest strips the API keys."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import CaptureSession, Document, Event, MediaAsset, Project, WorkflowGraphRow
from app.storage import store
from worker.pipeline.docgen_job import run_document_generate, run_document_snapshot

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _graph() -> dict:
    return {
        "workflow_id": "wf_doc",
        "version": 1,
        "title": "Doc test",
        "steps": [
            {"id": "s1", "action": "click", "target": "Settings", "intent": "Open settings",
             "screen_name": "Home", "selector": None, "screenshot": None, "bbox": [64, 36, 128, 72],
             "narration": "um first open settings", "t_start": 0.0, "t_end": 1.0,
             "confidence": 0.9, "review_status": "auto"},
            {"id": "s2", "action": "custom", "target": "Silence — add narration", "intent": "",
             "screen_name": "", "selector": None, "screenshot": None, "bbox": None,
             "narration": "", "t_start": 1.0, "t_end": 1.8, "confidence": 0.6, "review_status": "auto"},
            {"id": "s3", "action": "input", "target": "Name", "intent": "Type the name",
             "screen_name": "Settings", "selector": None, "screenshot": None, "bbox": [10, 10, 50, 20],
             "narration": "then type the name", "t_start": 1.8, "t_end": 2.8,
             "confidence": 0.9, "review_status": "auto"},
        ],
        "edges": [],
    }


def _setup(db, source_type: str = "extension", with_events: bool = True) -> tuple[Project, CaptureSession]:
    p = Project(name="Doc project")
    db.add(p)
    db.commit()
    db.refresh(p)
    sess = CaptureSession(project_id=p.id, source_type=source_type, telemetry="present" if with_events else "absent",
                          status="ready", viewport_json={"w": 1280, "h": 720}, duration_ms=3000)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    key = f"sessions/{sess.id}/source.mp4"
    out = store.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=10:duration=3",
         "-pix_fmt", "yuv420p", str(out)], capture_output=True, check=True,
    )
    db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=key))
    if with_events:
        db.add(Event(session_id=sess.id, seq=0, type="click", t_ms=300, bbox_json=[64, 36, 128, 72]))
        db.add(Event(session_id=sess.id, seq=1, type="input", t_ms=2000, bbox_json=[10, 10, 50, 20]))
    db.add(WorkflowGraphRow(project_id=p.id, version=1, graph_json=_graph()))
    db.add(Document(project_id=p.id, graph_version=1, doc_json={}, status="queued", doc_version=1))
    db.commit()
    return p, sess


def _doc(db, pid: str) -> Document:
    row = db.scalar(select(Document).where(Document.project_id == pid))
    db.refresh(row)
    return row


def test_generate_writes_ready_doc_with_annotated_snapshots():
    db = SessionLocal()
    try:
        p, sess = _setup(db)
        stats = run_document_generate(p.id, 1)
        assert stats["writer"] == "fallback" and stats["steps"] == 2 and stats["snapshots"] == 2

        row = _doc(db, p.id)
        assert row.status == "ready" and row.error_json is None and row.doc_json["version"] == 2
        ids = [s["id"] for s in row.doc_json["steps"]]
        assert ids == ["s1", "s3"]  # silence step skipped, graph order kept
        s1 = row.doc_json["steps"][0]
        assert s1["body"] == "First open settings."  # filler struck
        snap = s1["snapshot"]
        assert snap["t"] == 0.45  # click at 0.3s + 150ms offset
        assert snap["bbox_norm"] == [0.05, 0.05, 0.1, 0.1] and snap["pending"] is False
        assert store.local_path(snap["key"]).exists() and store.local_path(snap["raw_key"]).exists()
        assert snap["key"] != snap["raw_key"]
        assets = list(db.scalars(select(MediaAsset).where(MediaAsset.session_id == sess.id,
                                                          MediaAsset.kind == "docshot")))
        assert len(assets) == 2 and all(a.meta_json["annotated"] for a in assets)

        # the annotated frame differs from the raw one (the highlight was drawn)
        assert store.read(snap["key"]) != store.read(snap["raw_key"])
    finally:
        db.close()


def test_generate_skips_stale_or_already_ready_versions():
    db = SessionLocal()
    try:
        p, _ = _setup(db)
        assert run_document_generate(p.id, 99)["skipped"] == "stale"
        assert _doc(db, p.id).status == "queued"
        run_document_generate(p.id, 1)
        assert run_document_generate(p.id, 1)["skipped"] == "already ready"
        assert run_document_generate("nope", 1)["skipped"] == "not found"
    finally:
        db.close()


def test_recorder_and_upload_sessions_get_clean_frames():
    db = SessionLocal()
    try:
        p, _ = _setup(db, source_type="recorder")
        run_document_generate(p.id, 1)
        snaps = [s["snapshot"] for s in _doc(db, p.id).doc_json["steps"]]
        assert all(s and s["bbox_norm"] is None for s in snaps)
        # no highlight drawn: the display frame is byte-identical to the raw one
        assert all(store.read(s["key"]) == store.read(s["raw_key"]) for s in snaps)

        p2, _ = _setup(db, source_type="upload", with_events=False)
        run_document_generate(p2.id, 1)
        steps = _doc(db, p2.id).doc_json["steps"]
        assert steps[0]["snapshot"]["t"] == 0.5  # no click event: t_start + min(0.5, span/2)
        assert steps[0]["snapshot"]["bbox_norm"] is None
    finally:
        db.close()


def test_snapshot_regrab_replaces_only_that_step():
    db = SessionLocal()
    try:
        p, _ = _setup(db)
        run_document_generate(p.id, 1)
        row = _doc(db, p.id)
        before = row.doc_json["steps"][0]["snapshot"]["key"]
        # simulate the API: mark pending and edit text meanwhile
        row.doc_json["steps"][0]["snapshot"]["pending"] = True
        row.doc_json["steps"][1]["body"] = "Edited while grabbing."
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "doc_json")
        db.commit()

        r = run_document_snapshot(p.id, "s1", 2.5)
        assert r["ok"] and r["t"] == 2.5
        row = _doc(db, p.id)
        s1 = row.doc_json["steps"][0]["snapshot"]
        assert s1["key"] != before and s1["t"] == 2.5 and s1["pending"] is False
        assert s1["bbox_norm"] == [0.05, 0.05, 0.1, 0.1]  # still annotated from the graph bbox
        assert row.doc_json["steps"][1]["body"] == "Edited while grabbing."
        assert run_document_snapshot(p.id, "nope", 1.0)["skipped"] == "no such step"
        # beyond the end is clamped, not an error
        assert run_document_snapshot(p.id, "s3", 99.0)["t"] == 2.95
    finally:
        db.close()


def test_generate_records_error_when_graph_missing():
    db = SessionLocal()
    try:
        p, _ = _setup(db)
        db.execute(WorkflowGraphRow.__table__.delete().where(WorkflowGraphRow.project_id == p.id))
        db.commit()
        with pytest.raises(RuntimeError):
            run_document_generate(p.id, 1)
        row = _doc(db, p.id)
        assert row.status == "error" and "graph" in row.error_json["error"]
    finally:
        db.close()
