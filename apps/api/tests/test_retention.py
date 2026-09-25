"""Retention rules on the local backend: each deletes only what it should."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import CaptureSession, MediaAsset, Project, RenderJob, Upload, VideoProject
from app.retention import run_retention
from app.storage import store

OLD = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()


def _put(key: str, data: bytes = b"x" * 100, old: bool = True) -> str:
    store.write(key, data)
    if old:
        os.utime(store.local_path(key), (OLD, OLD))
    return key


def test_retention_rules():
    db = SessionLocal()
    p = Project(name="ret")
    db.add(p)
    db.commit()
    ready = CaptureSession(project_id=p.id, source_type="recorder", status="ready")
    busy = CaptureSession(project_id=p.id, source_type="recorder", status="processing")
    db.add_all([ready, busy])
    db.commit()

    orig = _put(f"sessions/{ready.id}/raw_video_a.webm")
    src = _put(f"sessions/{ready.id}/source.mp4")
    audio = _put(f"sessions/{ready.id}/audio.wav")
    fresh_orig = _put(f"sessions/{ready.id}/raw_video_b.webm", old=False)
    busy_orig = _put(f"sessions/{busy.id}/raw_video_c.webm")  # still processing: keep
    db.add_all([MediaAsset(session_id=ready.id, kind="raw_video", storage_key=src),
                MediaAsset(session_id=ready.id, kind="audio", storage_key=audio)])

    vp = VideoProject(project_id=p.id, graph_version=1, edit_spec_json={})
    db.add(vp)
    db.commit()
    old_render = _put(f"renders/{vp.id}/final_old.mp4")
    new_render = _put(f"renders/{vp.id}/final_new.mp4")  # newest: kept even though old
    j1 = RenderJob(video_project_id=vp.id, status="done", output_key=old_render,
                   created_at=datetime.now(timezone.utc) - timedelta(days=30))
    j2 = RenderJob(video_project_id=vp.id, status="done", output_key=new_render)
    tts = _put("tts/abc.wav")
    stale = Upload(session_id=ready.id, kind="raw_video", storage_key=f"sessions/{ready.id}/raw_video_z.webm",
                   backend_upload_id=store.mp_create("x"), size=10, part_size=5)
    db.add_all([j1, j2, stale])
    db.commit()
    stale.updated_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()
    stale_id, j1_id = stale.id, j1.id
    db.close()

    dry = run_retention(dry_run=True)
    assert dry["deleted"].get("originals") == 1 and store.exists(orig)  # dry run deletes nothing

    rep = run_retention()
    assert rep["deleted"]["originals"] == 1 and rep["deleted"]["audio"] == 1
    assert rep["deleted"]["old_renders"] == 1 and rep["deleted"]["tts_cache"] == 1
    assert rep["deleted"]["stale_uploads"] == 1
    assert not store.exists(orig) and not store.exists(audio) and not store.exists(old_render) and not store.exists(tts)
    for kept in (src, fresh_orig, busy_orig, new_render):
        assert store.exists(kept), kept
    db = SessionLocal()
    assert db.get(RenderJob, j1_id).output_key is None
    assert db.get(Upload, stale_id).status == "aborted"
    assert not db.query(MediaAsset).filter(MediaAsset.storage_key == audio).count()
    db.close()
