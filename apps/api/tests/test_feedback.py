"""Feedback is asked while a video or document generates — once per video and once
per document — needs only a star rating, and is readable only by admins."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Document, RenderJob, VideoProject
from tests.helpers import anon, make_client

admin_client = make_client("admin@example.com", name="Admin")


def _video(pid: str) -> str:
    with SessionLocal() as db:
        vp = VideoProject(project_id=pid, graph_version=1)
        db.add(vp)
        db.commit()
        return vp.id


def _render(vp_id: str, status: str) -> str:
    with SessionLocal() as db:
        job = RenderJob(video_project_id=vp_id, status=status)
        db.add(job)
        db.commit()
        return job.id


def _set_render(job_id: str, status: str) -> None:
    with SessionLocal() as db:
        db.get(RenderJob, job_id).status = status
        db.commit()


def test_required_first_then_skippable():
    c = make_client("feedback-video@example.com")
    pid = c.post("/projects", json={"name": "feedback-video"}).json()["id"]
    vp = _video(pid)
    assert c.get("/feedback/status").json() == {"due": None, "optional": None}

    job = _render(vp, "running")
    due = c.get("/feedback/status").json()["due"]
    assert due == {"kind": "video", "target_id": vp, "project_id": pid, "project_name": "feedback-video"}

    # only the rating is required; blank answers are stored as empty
    assert c.post("/feedback", json={"kind": "video", "target_id": vp}).status_code == 422
    assert c.post("/feedback", json={"kind": "video", "target_id": vp, "rating": 6}).status_code == 422
    r = c.post("/feedback", json={"kind": "video", "target_id": vp, "rating": 5, "challenges": "  "})
    assert r.status_code == 201, r.text
    assert r.json()["challenges"] is None and r.json()["email"] == "feedback-video@example.com"
    after = c.get("/feedback/status").json()
    assert after["due"] is None and after["optional"]["target_id"] == vp  # this run, already rated

    # regenerating the same video asks again, but optionally (the popup has Skip)
    _set_render(job, "done")
    assert c.get("/feedback/status").json() == {"due": None, "optional": None}
    assert c.post("/feedback", json={"kind": "video", "target_id": vp, "rating": 3}).status_code == 409
    job2 = _render(vp, "pending")
    status_ = c.get("/feedback/status").json()
    assert status_["due"] is None and status_["optional"]["target_id"] == vp
    assert c.post("/feedback", json={"kind": "video", "target_id": vp, "rating": 4}).status_code == 201
    _set_render(job2, "done")

    # a second video in the same project asks once more
    vp2 = _video(pid)
    _render(vp2, "running")
    assert c.get("/feedback/status").json()["due"]["target_id"] == vp2


def test_asked_for_a_generating_document():
    c = make_client("feedback-doc@example.com")
    pid = c.post("/projects", json={"name": "feedback-doc"}).json()["id"]
    with SessionLocal() as db:
        doc = Document(project_id=pid, graph_version=1, status="ready", doc_json={})
        db.add(doc)
        db.commit()
        doc_id = doc.id
    assert c.get("/feedback/status").json()["due"] is None  # finished work isn't asked about

    with SessionLocal() as db:
        db.get(Document, doc_id).status = "running"
        db.commit()
    assert c.get("/feedback/status").json()["due"]["kind"] == "doc"
    body = {"kind": "doc", "target_id": doc_id, "rating": 2, "improvements": "Faster screenshots"}
    assert c.post("/feedback", json=body).status_code == 201

    listing = admin_client.get("/admin/feedback").json()
    mine = next(i for i in listing["items"] if i["email"] == "feedback-doc@example.com")
    assert mine["project_name"] == "feedback-doc" and mine["improvements"] == "Faster screenshots"
    assert listing["average"] is not None


def test_feedback_is_private():
    owner = make_client("feedback-owner@example.com")
    pid = owner.post("/projects", json={"name": "feedback-private"}).json()["id"]
    vp = _video(pid)
    stranger = make_client("feedback-stranger@example.com")
    body = {"kind": "video", "target_id": vp, "rating": 1}
    assert stranger.post("/feedback", json=body).status_code == 404
    assert anon.get("/feedback/status").status_code == 401
    assert stranger.get("/admin/feedback").status_code == 403
