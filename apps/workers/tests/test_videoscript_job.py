"""The whole-recording Generate job, offline: the model (stubbed) is shown the
recording's frames window by window, the timed script lands on the session,
understanding is re-queued, and that run builds one scene per line at the
model's times. A failure is recorded on the Job and leaves the script alone."""

from __future__ import annotations

from refract_workflow_graph import validate
from sqlalchemy import select

from app import videoscript
from app.db import SessionLocal
from app.models import CaptureSession, Job, MediaAsset, Project, VideoProject, WorkflowGraphRow
from worker.pipeline import videoscript_job as vj
from worker.pipeline.run import run_pipeline


def _recording(db, seconds: int = 130) -> tuple[CaptureSession, Job]:
    p = Project(name="Create a Test Suite")
    db.add(p)
    db.commit()
    db.refresh(p)
    sess = CaptureSession(project_id=p.id, source_type="upload", telemetry="absent", status="ready",
                          duration_ms=seconds * 1000)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    for t in range(seconds):
        db.add(MediaAsset(session_id=sess.id, kind="frame",
                          storage_key=f"sessions/{sess.id}/frames/f{t:04d}.jpg", meta_json={"t": float(t)}))
    job = Job(session_id=sess.id, stage="script", version=0, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return sess, job


REPLIES = [
    '[{"t": 0, "line": "Meet TestEase, built for CPI testing."}, '
    '{"t": 10, "line": "Open Integrations from the dashboard."}]',
    '[{"t": 50, "line": "Choose the adapter type from the list."}]',
    '[{"t": 100, "line": "Click Create and the suite is ready to run."}]',
]


def test_job_writes_a_timed_script_and_the_pipeline_cuts_scenes_on_it(monkeypatch):
    db = SessionLocal()
    try:
        sess, job = _recording(db)
        calls: list[list] = []

        def fake_vision(system, parts, **kw):
            calls.append(parts)
            return REPLIES[len(calls) - 1]

        queued: list[str] = []
        monkeypatch.setattr(videoscript, "complete_vision", fake_vision)
        monkeypatch.setattr(vj, "frame_jpeg", lambda key: b"jpg")
        monkeypatch.setattr(vj, "has_llm", lambda: True)
        monkeypatch.setattr(vj, "enqueue_understanding", lambda sid: queued.append(sid))

        assert vj.run_video_script(sess.id, job.id, "A demo of TestEase", "fit", "Casual tone.") == {"lines": 4}

        # 130 frames -> three windows of 44/44/42, every frame shown once, in order
        assert [sum(isinstance(p, bytes) for p in parts) for parts in calls] == [44, 44, 42]
        assert "part 1 of 3" in calls[0][0] and "part 3 of 3" in calls[2][0]
        assert "Casual tone." in calls[0][0] and "A demo of TestEase" in calls[0][0]
        assert "covering 44.0s to 88.0s" in calls[1][0]
        # later windows see what was written before them
        assert "Open Integrations from the dashboard." in calls[1][0]
        assert "Choose the adapter type from the list." in calls[2][0]

        db.refresh(sess)
        db.refresh(job)
        assert job.status == "done" and job.progress == 1.0
        assert sess.script_text == (
            "[0:00.0] Meet TestEase, built for CPI testing.\n"
            "[0:10.0] Open Integrations from the dashboard.\n"
            "[0:50.0] Choose the adapter type from the list.\n"
            "[1:40.0] Click Create and the suite is ready to run."
        )
        assert queued == [sess.id]

        # the re-analysis the job queued: one scene per line, cut where the model said
        assert run_pipeline(sess.id)["steps"] == 4
        row = db.scalar(
            select(WorkflowGraphRow)
            .where(WorkflowGraphRow.project_id == sess.project_id)
            .order_by(WorkflowGraphRow.version.desc())
        )
        g = row.graph_json
        assert validate(g).valid
        steps = g["steps"]
        assert [s["t_start"] for s in steps] == [0.0, 10.0, 50.0, 100.0]
        assert steps[-1]["t_end"] == 130.0
        assert steps[2]["narration"] == "Choose the adapter type from the list."
    finally:
        db.close()


def test_job_keeps_a_trim_the_editor_made_in_its_scenes(monkeypatch):
    """The user cut 20–30 s in the editor (a skipped scene) and shortened the
    tail; Generate must not show the model that footage, and the rebuilt
    scenes must still leave it out."""
    db = SessionLocal()
    try:
        sess, job = _recording(db, seconds=40)
        spec = {"segments": [
            {"step_id": "s1", "source_start_ms": 0, "source_end_ms": 20000, "words": [], "removed": []},
            {"step_id": "s2", "source_start_ms": 20000, "source_end_ms": 30000, "words": [], "removed": [], "skipped": True},
            {"step_id": "s3", "source_start_ms": 30000, "source_end_ms": 36000, "words": [], "removed": []},
        ]}
        db.add(VideoProject(project_id=sess.project_id, graph_version=1, edit_spec_json=spec))
        db.commit()
        calls: list[list] = []

        def fake_vision(system, parts, **kw):
            calls.append(parts)
            return '[{"t": 0, "line": "Open the invoices tab to begin."}, {"t": 31, "line": "Export the invoice as a PDF."}]'

        queued: list[str] = []
        monkeypatch.setattr(videoscript, "complete_vision", fake_vision)
        monkeypatch.setattr(vj, "frame_jpeg", lambda key: key.encode())
        monkeypatch.setattr(vj, "has_llm", lambda: True)
        monkeypatch.setattr(vj, "enqueue_understanding", lambda sid: queued.append(sid))

        assert vj.run_video_script(sess.id, job.id, "A demo", "free")["lines"] == 2
        # only kept footage was shown: frames 0–20 s and 30–36 s, nothing from the cut
        shown = [p.decode() for p in calls[0] if isinstance(p, bytes)]
        times = [int(k.rsplit("f", 1)[1].split(".")[0]) for k in shown]
        assert times == list(range(0, 21)) + list(range(30, 37))
        db.refresh(sess)
        assert sess.keep_ranges_json == [[0, 20000], [30000, 36000]]
        assert queued == [sess.id]

        # the rebuild honours the stored ranges: no scene inside the cut
        assert run_pipeline(sess.id)["steps"] == 2
        row = db.scalar(
            select(WorkflowGraphRow)
            .where(WorkflowGraphRow.project_id == sess.project_id)
            .order_by(WorkflowGraphRow.version.desc())
        )
        steps = row.graph_json["steps"]
        assert [(s["t_start"], s["t_end"]) for s in steps] == [(0.0, 20.0), (30.0, 36.0)]
    finally:
        db.close()


def test_job_honours_an_editor_cut_made_after_keep_ranges_were_stored(monkeypatch):
    """An earlier Generate stored keep ranges; the user then skipped 5–10 s in
    the editor. The next Generate must not show the model that footage."""
    db = SessionLocal()
    try:
        sess, job = _recording(db, seconds=40)
        sess.keep_ranges_json = [[0, 20000], [30000, 36000]]
        spec = {"segments": [
            {"step_id": "s1", "source_start_ms": 0, "source_end_ms": 5000, "words": [], "removed": []},
            {"step_id": "s2", "source_start_ms": 5000, "source_end_ms": 10000, "words": [], "removed": [], "skipped": True},
            {"step_id": "s3", "source_start_ms": 10000, "source_end_ms": 20000, "words": [], "removed": []},
            {"step_id": "s4", "source_start_ms": 30000, "source_end_ms": 36000, "words": [], "removed": []},
        ]}
        db.add(VideoProject(project_id=sess.project_id, graph_version=1, edit_spec_json=spec))
        db.commit()
        calls: list[list] = []

        def fake_vision(system, parts, **kw):
            calls.append(parts)
            return '[{"t": 0, "line": "Open the invoices tab to begin."}, {"t": 31, "line": "Export the invoice as a PDF."}]'

        monkeypatch.setattr(videoscript, "complete_vision", fake_vision)
        monkeypatch.setattr(vj, "frame_jpeg", lambda key: key.encode())
        monkeypatch.setattr(vj, "has_llm", lambda: True)
        monkeypatch.setattr(vj, "enqueue_understanding", lambda sid: None)

        assert vj.run_video_script(sess.id, job.id, "A demo", "free")["lines"] == 2
        shown = [p.decode() for p in calls[0] if isinstance(p, bytes)]
        times = [int(k.rsplit("f", 1)[1].split(".")[0]) for k in shown]
        assert times == list(range(0, 6)) + list(range(10, 21)) + list(range(30, 37))
        db.refresh(sess)
        assert sess.keep_ranges_json == [[0, 5000], [10000, 20000], [30000, 36000]]
    finally:
        db.close()


def test_job_records_a_failure_and_keeps_the_script_untouched(monkeypatch):
    db = SessionLocal()
    try:
        sess, job = _recording(db, seconds=20)
        sess.script_text = "[0:00] The script the user had."
        db.commit()
        queued: list[str] = []
        monkeypatch.setattr(videoscript, "complete_vision", lambda *a, **k: "I cannot see any frames.")
        monkeypatch.setattr(vj, "frame_jpeg", lambda key: b"jpg")
        monkeypatch.setattr(vj, "has_llm", lambda: True)
        monkeypatch.setattr(vj, "enqueue_understanding", lambda sid: queued.append(sid))

        out = vj.run_video_script(sess.id, job.id, "A demo", "free")
        assert "could not be read" in out["error"]
        db.refresh(sess)
        db.refresh(job)
        assert job.status == "error" and "could not be read" in job.message
        assert sess.script_text == "[0:00] The script the user had."
        assert queued == []

        # without a key the job says so instead of calling anything
        monkeypatch.setattr(vj, "has_llm", lambda: False)
        assert "no AI key" in vj.run_video_script(sess.id, job.id, "A demo", "free")["error"]
    finally:
        db.close()
