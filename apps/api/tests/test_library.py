"""Media library: upload handshakes, ownership (404 never 403), background
removal / import requests, and the edit-spec guard that stops a project
pointing the renderer at someone else's media."""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.routers import library as library_router
from app.storage import store
from tests.helpers import client, other_client

MB = 1024 * 1024


@pytest.fixture
def enqueued(monkeypatch):
    calls: list[tuple[str, str]] = []
    for name in ("enqueue_library_process", "enqueue_library_remove_bg", "enqueue_library_import"):
        monkeypatch.setattr(library_router, name, lambda aid, _n=name: calls.append((_n, aid)))
    return calls


def _upload_small(name="logo.png", data=b"\x89PNG fake image bytes") -> dict:
    a = client.post("/library", json={"name": name, "ext": name.rsplit(".", 1)[1], "size": len(data)}).json()
    assert a["put_url"] == f"/media/library/{a['id']}/original.{name.rsplit('.', 1)[1]}"
    assert client.put(a["put_url"], content=data).status_code == 204
    return a


def test_single_put_upload_then_processing_is_enqueued(enqueued):
    a = _upload_small()
    assert a["kind"] == "image" and a["status"] == "uploading"
    # still uploading: hidden from the library list
    assert all(x["id"] != a["id"] for x in client.get("/library").json())
    r = client.post(f"/library/{a['id']}/uploaded")
    assert r.status_code == 200 and r.json()["status"] == "processing"
    assert enqueued == [("enqueue_library_process", a["id"])]
    assert any(x["id"] == a["id"] for x in client.get("/library?kind=image").json())
    assert all(x["id"] != a["id"] for x in client.get("/library?kind=video").json())


def test_kinds_and_rejected_types():
    for ext, kind in (("mov", "video"), ("heic", "image"), ("mp3", "audio"), ("svg", "image")):
        r = client.post("/library", json={"name": f"f.{ext}", "ext": ext, "size": 10})
        assert r.status_code == 201 and r.json()["kind"] == kind
    assert client.post("/library", json={"name": "x.exe", "ext": "exe", "size": 10}).status_code == 422


def test_multipart_upload_for_large_files(enqueued):
    part = get_settings().upload_part_mb * MB
    size = library_router.SINGLE_PUT_MAX + 10
    a = client.post("/library", json={"name": "clip.mp4", "ext": "mp4", "size": size}).json()
    assert a["upload_id"] and a["part_count"] == -(-size // a["part_size"]) and a["part_size"] >= part
    aid = a["id"]
    data = os.urandom(size)
    etags = []
    for n in range(1, a["part_count"] + 1):
        url = client.post(f"/library/{aid}/parts/sign", json={"numbers": [n]}).json()["parts"][0]["url"]
        chunk = data[(n - 1) * a["part_size"]: n * a["part_size"]]
        etags.append({"number": n, "etag": client.put(url, content=chunk).json()["etag"]})
    assert [p["number"] for p in client.get(f"/library/{aid}/parts").json()["parts"]] == list(range(1, a["part_count"] + 1))
    done = client.post(f"/library/{aid}/complete", json={"parts": etags})
    assert done.status_code == 200 and done.json()["status"] == "processing"
    assert store.read(f"library/{aid}/original.mp4") == data


def test_other_users_cannot_see_or_touch_an_asset(enqueued):
    a = _upload_small()
    aid = a["id"]
    assert other_client.post(f"/library/{aid}/uploaded").status_code == 404
    assert other_client.patch(f"/library/{aid}", json={"name": "mine"}).status_code == 404
    assert other_client.delete(f"/library/{aid}").status_code == 404
    assert other_client.put(f"/media/library/{aid}/original.png", content=b"x").status_code == 404
    # the owner may only write the original, not invent other keys under the asset
    assert client.put(f"/media/library/{aid}/nobg.png", content=b"x").status_code == 403
    assert all(x["id"] != aid for x in other_client.get("/library").json())


def test_remove_bg_rules_and_delete(enqueued):
    a = _upload_small()
    aid = a["id"]
    client.post(f"/library/{aid}/uploaded")
    assert client.post(f"/library/{aid}/remove-bg").status_code == 409  # still processing
    from app.db import SessionLocal
    from app.models import LibraryAsset

    with SessionLocal() as db:
        db.get(LibraryAsset, aid).status = "ready"
        db.commit()
    r = client.post(f"/library/{aid}/remove-bg")
    assert r.status_code == 202 and r.json()["bg_status"] == "running"
    assert ("enqueue_library_remove_bg", aid) in enqueued

    v = client.post("/library", json={"name": "c.mp4", "ext": "mp4", "size": 5}).json()
    assert client.post(f"/library/{v['id']}/remove-bg").status_code == 400

    assert client.patch(f"/library/{aid}", json={"name": "Brand logo"}).json()["name"] == "Brand logo"
    assert client.delete(f"/library/{aid}").status_code == 204
    assert not store.exists(f"library/{aid}/original.png")


def test_reuse_a_recording_from_another_project(enqueued):
    pid = client.post("/projects", json={"name": "Earlier demo"}).json()["id"]
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]
    assert client.post("/library/import-recording", json={"session_id": sid}).status_code == 409  # no video yet
    target = client.post(f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "mp4"}).json()
    client.put(target["upload_url"] if "upload_url" in target else target["url"], content=b"video")
    recs = client.get("/library/recordings").json()
    assert any(r["session_id"] == sid and r["project_name"] == "Earlier demo" for r in recs)
    assert all(r["session_id"] != sid for r in other_client.get("/library/recordings").json())
    assert other_client.post("/library/import-recording", json={"session_id": sid}).status_code == 404
    r = client.post("/library/import-recording", json={"session_id": sid})
    assert r.status_code == 202 and r.json()["source"] == "recording" and r.json()["kind"] == "video"
    assert ("enqueue_library_import", r.json()["id"]) in enqueued


def test_video_spec_only_accepts_media_the_editor_may_use(enqueued, monkeypatch):
    import app.routers.video as video_router

    monkeypatch.setattr(video_router, "enqueue_voice_track", lambda *a, **k: None)
    pid = client.post("/projects", json={"name": "spec guard"}).json()["id"]
    from app.db import SessionLocal
    from app.models import VideoProject, WorkflowGraphRow

    with SessionLocal() as db:
        db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json={"version": 1, "title": "t", "steps": []}))
        db.add(VideoProject(project_id=pid, graph_version=1, edit_spec_json={"segments": []}))
        db.commit()
    mine = _upload_small()
    theirs = other_client.post("/library", json={"name": "t.png", "ext": "png", "size": 3}).json()

    def patch(spec):
        return client.patch(f"/projects/{pid}/video", json={"edit_spec": {"segments": [], **spec}})

    ok = patch({"overlays": [{"id": "o", "type": "image", "media_key": f"library/{mine['id']}/normalized.png"}],
                "inserts": [{"id": "i", "type": "image", "media_key": f"projects/{pid}/intro.png", "position": "start"}],
                "music": {"enabled": True, "storage_key": f"library/{mine['id']}/original.mp3"}})
    assert ok.status_code == 200, ok.text
    bad = patch({"overlays": [{"id": "o", "type": "image", "media_key": f"library/{theirs['id']}/normalized.png"}]})
    assert bad.status_code == 422
    assert patch({"music": {"enabled": True, "storage_key": "projects/other/music.mp3"}}).status_code == 422
