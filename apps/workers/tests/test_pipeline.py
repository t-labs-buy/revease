import shutil
import subprocess

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import CaptureSession, Event, MediaAsset, Project, WorkflowGraphRow
from app.storage import store
from worker.pipeline.run import _persist_graph, run_pipeline


def _project(db, name="p") -> Project:
    p = Project(name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_persist_graph_idempotent_by_project_version():
    db = SessionLocal()
    try:
        p = _project(db, "idem")
        g = {"workflow_id": "w", "version": 1, "title": "T", "steps": [], "edges": []}
        _persist_graph(db, p.id, 1, g)
        _persist_graph(db, p.id, 1, {**g, "title": "T2"})  # same version -> upsert
        rows = db.scalars(
            select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == p.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].graph_json["title"] == "T2"
    finally:
        db.close()


def test_pipeline_extension_session_yields_valid_graph():
    db = SessionLocal()
    try:
        p = _project(db, "ext")
        sess = CaptureSession(
            project_id=p.id, source_type="extension", telemetry="present", status="captured",
            duration_ms=6000,
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)
        for i, t in enumerate([1000, 3000, 5000]):
            db.add(Event(session_id=sess.id, seq=i, type="click", t_ms=t, selector=f"#b{i}", text=f"Button {i}", bbox_json=[i, i, 8, 8]))
        db.commit()

        result = run_pipeline(sess.id)
        assert result["steps"] == 3

        row = db.scalar(
            select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == p.id)
        )
        from refract_workflow_graph import validate

        assert validate(row.graph_json).valid
        assert len(row.graph_json["steps"]) == 3
        db.refresh(sess)
        assert sess.status == "ready"
    finally:
        db.close()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_pipeline_media_stage_extracts_frames_from_real_video():
    db = SessionLocal()
    try:
        p = _project(db, "vid")
        sess = CaptureSession(
            project_id=p.id, source_type="upload", telemetry="absent", status="captured"
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)

        # Synthesize a 2s test video with an audio tone into the media store.
        key = f"sessions/{sess.id}/raw_video.mp4"
        out = store.local_path(key)
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest",
             "-pix_fmt", "yuv420p", str(out)],
            capture_output=True, check=True,
        )
        db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=key))
        db.commit()

        run_pipeline(sess.id)

        frames = db.scalar(
            select(func.count()).select_from(MediaAsset).where(
                MediaAsset.session_id == sess.id, MediaAsset.kind == "frame"
            )
        )
        assert frames >= 1  # ffmpeg produced keyframes
        row = db.scalar(select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == p.id))
        from refract_workflow_graph import validate

        assert validate(row.graph_json).valid
    finally:
        db.close()
