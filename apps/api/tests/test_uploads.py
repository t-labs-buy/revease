"""Resumable multipart uploads on the local backend: create, resume, complete,
ownership, and the size/part checks that stop a truncated file being processed."""

from __future__ import annotations

import os

from app.config import get_settings
from app.storage import store
from tests.helpers import client, other_client

MB = 1024 * 1024


def _session() -> str:
    pid = client.post("/projects", json={"name": "big upload"}).json()["id"]
    return client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]


def test_multipart_upload_resume_and_complete():
    sid = _session()
    part = get_settings().upload_part_mb * MB
    data = os.urandom(part * 2 + 1234)  # 3 parts, the last one short
    up = client.post(f"/sessions/{sid}/uploads", json={"kind": "raw_video", "ext": "webm", "size": len(data)}).json()
    assert up["part_count"] == 3 and up["part_size"] == part
    uid = up["upload_id"]

    signed = client.post(f"/uploads/{uid}/parts/sign", json={"numbers": [1, 2, 3]}).json()["parts"]
    assert signed[0]["url"] == f"/uploads/{uid}/parts/1" and signed[0]["direct"] is False

    etags = {}
    r = client.put(f"/uploads/{uid}/parts/1", content=data[:part])
    etags[1] = r.json()["etag"]

    # "connection lost": the client asks what already arrived and resumes
    status = client.get(f"/uploads/{uid}").json()
    assert [p["number"] for p in status["parts"]] == [1] and status["parts"][0]["size"] == part

    # completing early is refused
    assert client.post(f"/uploads/{uid}/complete", json={"parts": [{"number": 1, "etag": etags[1]}]}).status_code == 422
    for n, chunk in ((2, data[part:2 * part]), (3, data[2 * part:])):
        etags[n] = client.put(f"/uploads/{uid}/parts/{n}", content=chunk).json()["etag"]

    done = client.post(f"/uploads/{uid}/complete",
                       json={"parts": [{"number": n, "etag": e} for n, e in etags.items()]})
    assert done.status_code == 200, done.text
    key = done.json()["storage_key"]
    assert key.startswith(f"sessions/{sid}/raw_video_") and store.read(key) == data
    detail = client.get(f"/sessions/{sid}").json()
    assert any(a["kind"] == "raw_video" and a["storage_key"] == key for a in detail["assets"])
    # idempotent
    assert client.post(f"/uploads/{uid}/complete", json={"parts": [{"number": 1, "etag": "x"}]}).json()["storage_key"] == key


def test_upload_is_owner_only_and_validates_parts():
    sid = _session()
    up = client.post(f"/sessions/{sid}/uploads", json={"kind": "raw_video", "ext": "mp4", "size": 10}).json()
    uid = up["upload_id"]
    assert other_client.get(f"/uploads/{uid}").status_code == 404
    assert other_client.put(f"/uploads/{uid}/parts/1", content=b"x" * 10).status_code == 404
    assert client.post(f"/uploads/{uid}/parts/sign", json={"numbers": [2]}).status_code == 422
    client.put(f"/uploads/{uid}/parts/1", content=b"x" * 9)  # one byte short
    etag = client.get(f"/uploads/{uid}").json()["parts"][0]["etag"]
    r = client.post(f"/uploads/{uid}/complete", json={"parts": [{"number": 1, "etag": etag}]})
    assert r.status_code == 409 and "expected 10" in r.json()["detail"]
    assert client.delete(f"/uploads/{uid}").status_code == 204
    assert client.put(f"/uploads/{uid}/parts/1", content=b"x").status_code == 409
    assert other_client.post(f"/sessions/{sid}/uploads", json={"ext": "mp4", "size": 5}).status_code == 404


def test_download_original_then_fallback_to_processed():
    from app.db import SessionLocal
    from app.models import MediaAsset

    sid = _session()
    pid = client.get(f"/sessions/{sid}").json()["project_id"]
    client.patch(f"/projects/{pid}", json={"name": "Démo onboarding"})
    orig = store.write(f"sessions/{sid}/raw_video_abc.webm", b"webm-bytes")
    db = SessionLocal()
    db.add(MediaAsset(session_id=sid, kind="raw_video", storage_key=f"sessions/{sid}/source.mp4"))
    db.commit()
    db.close()
    store.write(f"sessions/{sid}/source.mp4", b"mp4-bytes")

    d = client.get(f"/sessions/{sid}/download").json()
    assert d["variant"] == "original" and d["fallback"] is False and d["filename"].endswith("-original.webm")
    r = client.get(d["url"])
    assert r.content == b"webm-bytes" and r.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]

    p = client.get(f"/sessions/{sid}/download", params={"variant": "processed"}).json()
    assert p["variant"] == "processed" and client.get(p["url"]).content == b"mp4-bytes"

    store.delete(orig)  # retention removed the original
    f = client.get(f"/sessions/{sid}/download").json()
    assert f["variant"] == "processed" and f["fallback"] is True
    assert other_client.get(f"/sessions/{sid}/download").status_code == 404
