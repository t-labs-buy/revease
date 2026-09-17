from app.db import SessionLocal
from app.models import RenderJob, VideoProject, WorkflowGraphRow
from tests.helpers import client

GRAPH = {
    "workflow_id": "wf_s", "version": 1, "title": "Shared Demo",
    "steps": [{"id": "s1", "action": "click", "target": "Go", "narration": "Go."}],
    "edges": [],
}


def _project() -> str:
    return client.post("/projects", json={"name": "share"}).json()["id"]


def test_share_video_requires_render_then_public_view():
    pid = _project()
    # graph + a completed render
    db = SessionLocal()
    db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json=GRAPH))
    vp = VideoProject(project_id=pid, graph_version=1, edit_spec_json={})
    db.add(vp)
    db.commit()
    db.refresh(vp)

    # can't share a video before it's rendered
    assert client.post(f"/projects/{pid}/share", json={"kind": "video"}).status_code == 400

    db.add(RenderJob(video_project_id=vp.id, status="done", output_key="renders/x/final.mp4"))
    db.commit()
    db.close()

    r = client.post(f"/projects/{pid}/share", json={"kind": "video"})
    assert r.status_code == 200
    token = r.json()["token"]

    # sharing again returns the same active link
    assert client.post(f"/projects/{pid}/share", json={"kind": "video"}).json()["token"] == token

    pub = client.get(f"/shares/{token}")
    assert pub.status_code == 200
    assert pub.json()["kind"] == "video"
    assert pub.json()["video_url"].endswith("final.mp4")
    assert pub.json()["title"] == "Shared Demo"
    # download is hidden by default
    assert pub.json()["allow_download"] is False

    # owner turns download on; public page reflects it
    upd = client.patch(f"/shares/{token}", json={"allow_download": True})
    assert upd.status_code == 200 and upd.json()["allow_download"] is True
    assert client.get(f"/shares/{token}").json()["allow_download"] is True

    # re-sharing with an explicit value updates the same link; omitting it keeps it
    r = client.post(f"/projects/{pid}/share", json={"kind": "video", "allow_download": False})
    assert r.json()["token"] == token and r.json()["allow_download"] is False
    assert client.post(f"/projects/{pid}/share", json={"kind": "video"}).json()["allow_download"] is False
    assert client.patch("/shares/nope", json={"allow_download": True}).status_code == 404

    # listed + revocable
    assert any(s["token"] == token for s in client.get(f"/projects/{pid}/shares").json())
    assert client.delete(f"/shares/{token}").status_code == 200
    assert client.get(f"/shares/{token}").status_code == 404


def test_share_doc_public_view():
    pid = _project()
    db = SessionLocal()
    db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json=GRAPH))
    db.commit()
    db.close()
    token = client.post(f"/projects/{pid}/share", json={"kind": "doc"}).json()["token"]
    pub = client.get(f"/shares/{token}").json()
    assert pub["kind"] == "doc" and pub["doc"]["title"] == "Shared Demo"


def test_share_unknown_token_404():
    assert client.get("/shares/nope").status_code == 404
