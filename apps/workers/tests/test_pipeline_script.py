"""End-to-end pipeline for a recording with a user-supplied script — offline
(conftest strips the API keys, so timing is the proportional fallback and the
click path uses the deterministic even split)."""

from refract_workflow_graph import validate
from sqlalchemy import select

from app.db import SessionLocal
from app.models import CaptureSession, Event, MediaAsset, Project, Transcript, WorkflowGraphRow
from worker.pipeline import run as run_mod
from worker.pipeline.run import run_pipeline

SCRIPT = (
    "Welcome to the billing dashboard. Open the invoices tab to see every invoice. "
    "[0:20] Click an invoice to view its line items. Finally, download it as a PDF."
)
SPOKEN = SCRIPT.replace("[0:20] ", "")


def _session(db, *, script=None, telemetry="absent", source="upload", duration_ms=40_000) -> CaptureSession:
    p = Project(name="scripted")
    db.add(p)
    db.commit()
    db.refresh(p)
    sess = CaptureSession(project_id=p.id, source_type=source, telemetry=telemetry,
                          status="captured", duration_ms=duration_ms, script_text=script)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def _graph(db, sess):
    row = db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == sess.project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )
    return row.graph_json


def test_silent_upload_with_script_gets_one_scene_per_line():
    db = SessionLocal()
    try:
        sess = _session(db, script=SCRIPT)
        for t in range(0, 40, 2):
            db.add(MediaAsset(session_id=sess.id, kind="frame",
                              storage_key=f"sessions/{sess.id}/frames/f{t}.jpg", meta_json={"t": float(t)}))
        db.commit()

        assert run_pipeline(sess.id)["steps"] == 4
        g = _graph(db, sess)
        assert validate(g).valid
        steps = g["steps"]
        # narration is the script, word for word, timestamps removed
        assert " ".join(s["narration"] for s in steps).split() == SPOKEN.split()
        # windows partition the whole recording, and the pinned line starts on its mark
        assert steps[0]["t_start"] == 0.0 and steps[-1]["t_end"] == 40.0
        assert all(a["t_end"] == b["t_start"] for a, b in zip(steps, steps[1:]))
        assert steps[2]["t_start"] == 20.0
        assert all(s["screenshot"] for s in steps)

        tr = db.scalar(select(Transcript).where(Transcript.session_id == sess.id))
        assert tr.provider == "user" and tr.text == SPOKEN
        db.refresh(sess)
        assert sess.status == "ready"
    finally:
        db.close()


def test_script_on_a_click_session_keeps_the_click_steps():
    db = SessionLocal()
    try:
        sess = _session(db, script=SCRIPT, telemetry="present", source="extension", duration_ms=9000)
        for i, t in enumerate([1000, 4000, 7000]):
            db.add(Event(session_id=sess.id, seq=i, type="click", t_ms=t,
                         selector=f"#b{i}", text=f"Item {i}", bbox_json=[i, i, 8, 8]))
        db.commit()

        assert run_pipeline(sess.id)["steps"] == 3
        steps = _graph(db, sess)["steps"]
        assert [s["t_start"] for s in steps] == [0.0, 4.0, 7.0]  # boundaries are the clicks
        assert all(s["bbox"] for s in steps)
        assert " ".join(s["narration"] for s in steps if s["narration"]).split() == SPOKEN.split()
    finally:
        db.close()


def test_silent_upload_without_script_stays_empty_offline():
    db = SessionLocal()
    try:
        sess = _session(db)
        for t in range(0, 40, 2):
            db.add(MediaAsset(session_id=sess.id, kind="frame",
                              storage_key=f"sessions/{sess.id}/frames/f{t}.jpg", meta_json={"t": float(t)}))
        db.commit()
        run_pipeline(sess.id)
        steps = _graph(db, sess)["steps"]
        assert steps and all(s["narration"] == "" for s in steps)
    finally:
        db.close()


def test_silent_upload_without_script_follows_screen_changes_and_stays_empty(monkeypatch):
    """Scenes follow the detected screen changes, and the pipeline writes no
    narration of its own — that is the editor's Generate button."""
    monkeypatch.setattr(run_mod, "_scene_cuts", lambda db, sess, spans: [12.0, 30.0])
    db = SessionLocal()
    try:
        sess = _session(db)
        for t in range(0, 40, 2):
            db.add(MediaAsset(session_id=sess.id, kind="frame",
                              storage_key=f"sessions/{sess.id}/frames/f{t}.jpg", meta_json={"t": float(t)}))
        db.commit()
        run_pipeline(sess.id)
        steps = _graph(db, sess)["steps"]
        assert [(s["t_start"], s["t_end"]) for s in steps] == [(0.0, 12.0), (12.0, 30.0), (30.0, 40.0)]
        assert all(s["narration"] == "" for s in steps)
    finally:
        db.close()

