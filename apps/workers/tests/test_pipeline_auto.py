"""End-to-end pipeline for an Auto Record session, no browser and no LLM (conftest
strips API keys, so narration uses the deterministic even split)."""

from refract_workflow_graph import validate
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AutoRecordRun, CaptureSession, Event, Project, Transcript, WorkflowGraphRow
from worker.pipeline.run import run_pipeline


def _project(db, name="auto") -> Project:
    p = Project(name=name)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_auto_session_builds_graph_from_agent_log_and_transcript():
    db = SessionLocal()
    try:
        p = _project(db)
        sess = CaptureSession(
            project_id=p.id, source_type="auto", telemetry="present", status="captured",
            duration_ms=8000,
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)

        # Telemetry events the extension uploaded (seq == decision index).
        for i, t in enumerate([500, 3000, 6000]):
            db.add(Event(session_id=sess.id, seq=i, type="click", t_ms=t,
                         selector=f"#b{i}", text=f"Item {i}", bbox_json=[i, i, 8, 8]))
        db.commit()

        transcript = "Welcome to the demo. Now we open the dashboard. Finally we save our work."
        agent_log = [
            {"index": 0, "action": "click", "ok": True, "target": "Home",
             "intent": "Open home", "screen_name": "Home", "selector": "#b0",
             "bbox": [0, 0, 8, 8], "plan_item_id": "p1"},
            {"index": 1, "action": "click", "ok": True, "target": "Dashboard",
             "intent": "Open dashboard", "screen_name": "Dashboard", "selector": "#b1",
             "bbox": [1, 1, 8, 8], "plan_item_id": "p2"},
            {"index": 2, "action": "wait", "ok": True},  # control flow -> not a step
            {"index": 3, "action": "click", "ok": False, "error": "stale"},  # dropped
            {"index": 2, "action": "click", "ok": True, "target": "Save",
             "intent": "Save work", "screen_name": "Dashboard", "selector": "#b2",
             "bbox": [2, 2, 8, 8], "plan_item_id": "p3"},
        ]
        db.add(AutoRecordRun(
            project_id=p.id, session_id=sess.id, status="capture_done",
            coverage_plan_json=[{"id": "p1", "text": "Home", "status": "done"},
                                {"id": "p2", "text": "Dashboard", "status": "done"},
                                {"id": "p3", "text": "Save", "status": "done"}],
            transcript_text=transcript, agent_log_json=agent_log,
        ))
        db.commit()

        result = run_pipeline(sess.id)
        assert result["steps"] == 3  # wait + errored entries dropped

        row = db.scalar(select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == p.id))
        g = row.graph_json
        assert validate(g).valid
        # semantics came straight from the agent log (no LLM inference)
        assert [s["intent"] for s in g["steps"]] == ["Open home", "Open dashboard", "Save work"]
        # narration is a verbatim partition of the transcript across the steps
        joined = " ".join(s["narration"] for s in g["steps"] if s["narration"]).split()
        assert joined == transcript.split()

        # user transcript persisted (provider='user'), whisper skipped
        tr = db.scalar(select(Transcript).where(Transcript.session_id == sess.id))
        assert tr.provider == "user" and tr.text == transcript

        db.refresh(sess)
        run = db.scalar(select(AutoRecordRun).where(AutoRecordRun.session_id == sess.id))
        assert sess.status == "ready" and run.status == "ready"
    finally:
        db.close()
