"""Pipeline progress summary, the session status fields, the reprocess guard
and the activity feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import CaptureSession, Document, Job
from app.progress import summarize
from app.routers import sessions as sessions_router
from tests.helpers import client, other_client

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@dataclass
class J:
    stage: str
    status: str
    progress: float | None = None
    message: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None


def test_summary_weights_running_stage_and_estimates_eta():
    jobs = [J("media", "running", 0.5, "Converting video · 05:00 of 10:00",
              started_at=NOW - timedelta(minutes=10), updated_at=NOW - timedelta(seconds=5))]
    s = summarize(jobs, now=NOW)
    assert s.stage == "media" and s.message.startswith("Converting")
    assert s.progress == 0.25  # media weight 0.5 * 50%
    # 10 min for half the media stage: 10 more for media + whisper/merge/extract priced by weight
    assert s.eta_s == 600 + round(1200 / 0.5 * 0.5)
    assert s.elapsed_s == 600 and not s.stalled


def test_summary_withholds_eta_early_and_flags_stalls():
    early = summarize([J("media", "running", 0.01, started_at=NOW - timedelta(minutes=5),
                         updated_at=NOW)], now=NOW)
    assert early.eta_s is None
    stalled = summarize([J("media", "running", 0.4, started_at=NOW - timedelta(minutes=30),
                           updated_at=NOW - timedelta(minutes=10))], now=NOW)
    assert stalled.stalled


def test_summary_counts_error_stages_as_passed_and_completes():
    jobs = [J("media", "error"), J("whisper", "done"), J("merge", "done"), J("extract", "running", 0.0,
            started_at=NOW, updated_at=NOW)]
    assert summarize(jobs, now=NOW).progress == 0.82
    done = [J(s, "done") for s in ("media", "whisper", "merge", "extract")]
    assert summarize(done, now=NOW).progress == 1.0


def _session(status: str = "processing") -> tuple[str, str]:
    pid = client.post("/projects", json={"name": "Long recording"}).json()["id"]
    db = SessionLocal()
    sess = CaptureSession(project_id=pid, source_type="recorder", status=status, duration_ms=1_726_000)
    db.add(sess)
    db.commit()
    sid = sess.id
    db.add(Job(session_id=sid, stage="media", version=1, status="running", attempts=1, progress=0.4,
               message="Converting video · 11:30 of 28:46",
               started_at=datetime.now(timezone.utc) - timedelta(minutes=20)))
    db.commit()
    db.close()
    return pid, sid


def test_session_status_reports_progress_message_and_eta():
    _, sid = _session()
    r = client.get(f"/sessions/{sid}/status").json()
    assert r["stage"] == "media" and r["message"].startswith("Converting video")
    assert r["progress"] == 0.2 and r["eta_s"] > 0 and r["stalled"] is False
    assert r["jobs"][0]["progress"] == 0.4 and r["jobs"][0]["started_at"]


def test_reprocess_refused_while_running(monkeypatch):
    calls = []
    monkeypatch.setattr(sessions_router, "enqueue_understanding", lambda sid: calls.append(sid))
    _, sid = _session()
    assert client.post(f"/sessions/{sid}/reprocess").status_code == 409 and calls == []


def test_activity_lists_processing_and_documents_for_owner_only():
    pid, sid = _session()
    db = SessionLocal()
    db.add(Document(project_id=pid, graph_version=1, doc_json={}, status="running", doc_version=1,
                    progress=0.5, message="Capturing snapshot 3 of 6…"))
    db.commit()
    db.close()
    items = client.get("/activity").json()
    mine = [i for i in items if i["project_id"] == pid]
    kinds = {i["kind"]: i for i in mine}
    assert kinds["processing"]["href"] == f"/projects/{pid}/prepare?sid={sid}"
    assert kinds["processing"]["message"].startswith("Converting video")
    assert kinds["document"]["progress"] == 0.5
    assert not [i for i in other_client.get("/activity").json() if i["project_id"] == pid]
