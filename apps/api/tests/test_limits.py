"""Per-video limits (500 MB / 30 min): every entry point refuses oversize
captures with a message that tells the user to split the video."""

from __future__ import annotations

from app.config import get_settings
from app.limits import duration_error
from app.storage import store
from tests.helpers import client

MB = 1024 * 1024


def _session() -> str:
    pid = client.post("/projects", json={"name": "limits"}).json()["id"]
    return client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]


def test_multipart_upload_over_500mb_is_refused_with_a_split_hint():
    sid = _session()
    r = client.post(f"/sessions/{sid}/uploads", json={"kind": "raw_video", "ext": "mp4", "size": 501 * MB})
    assert r.status_code == 413 and "split it" in r.json()["detail"] and "500 MB" in r.json()["detail"]
    ok = client.post(f"/sessions/{sid}/uploads", json={"kind": "raw_video", "ext": "mp4", "size": 499 * MB})
    assert ok.status_code == 201


def test_library_upload_over_500mb_is_refused():
    r = client.post("/library", json={"name": "big.mov", "ext": "mov", "size": 600 * MB})
    assert r.status_code == 413


def test_single_put_is_capped_while_streaming(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_video_mb", 1)
    sid = _session()
    target = client.post(f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "webm"}).json()
    r = client.put(target["url"], content=b"x" * (MB + 10))
    assert r.status_code == 413
    assert not store.exists(target["storage_key"])  # the partial file is removed


def test_capture_longer_than_30_minutes_is_refused_but_a_little_over_is_fine():
    sid = _session()
    r = client.post(f"/sessions/{sid}/complete", json={"duration_ms": 45 * 60_000})
    assert r.status_code == 422 and "30 minutes" in r.json()["detail"]
    # the recorder stops at 29:58; a few hundred ms of container overhead passes
    assert duration_error(30 * 60_000 + 500) is None
    assert client.post(f"/sessions/{sid}/complete", json={"duration_ms": 30 * 60_000 + 500}).status_code == 200
