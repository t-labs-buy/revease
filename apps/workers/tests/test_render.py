import shutil
import subprocess

import pytest

from app.db import SessionLocal
from app.editspec import build_edit_spec, mark_dirty
from app.models import CaptureSession, MediaAsset, Project, RenderJob, VideoProject
from app.storage import store
from worker.pipeline.render import run_render

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _graph(n=3):
    steps = []
    for i in range(n):
        steps.append({
            "id": f"s{i+1}", "action": "click", "target": f"Button {i+1}",
            "bbox": [200 + i * 100, 150, 120, 40], "screenshot": None,
            "narration": f"Click button {i + 1} to continue.",
            "t_start": float(i), "t_end": float(i) + 1.0, "confidence": 0.9,
        })
    return {"workflow_id": "wf_r", "version": 1, "title": "Render Test", "steps": steps,
            "edges": [{"from": f"s{i}", "to": f"s{i+1}", "condition": None} for i in range(1, n)]}


def _probe_s(key: str) -> float:
    p = store.local_path(key)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _setup(db) -> VideoProject:
    p = Project(name="render")
    db.add(p)
    db.commit()
    db.refresh(p)
    sess = CaptureSession(project_id=p.id, source_type="upload", telemetry="absent",
                          status="ready", viewport_json={"w": 1280, "h": 720})
    db.add(sess)
    db.commit()
    db.refresh(sess)
    # real 3s source video
    key = f"sessions/{sess.id}/raw_video.mp4"
    out = store.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=10:duration=3",
         "-pix_fmt", "yuv420p", str(out)], capture_output=True, check=True,
    )
    db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=key))
    spec = build_edit_spec(_graph(3), {"w": 1280, "h": 720})
    vp = VideoProject(project_id=p.id, graph_version=1, edit_spec_json=spec)
    db.add(vp)
    db.commit()
    db.refresh(vp)
    return vp


def test_render_is_drift_free_and_regenerate_touches_only_changed():
    db = SessionLocal()
    try:
        vp = _setup(db)

        # ---- initial render ----
        job1 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job1)
        db.commit()
        db.refresh(job1)
        stats1 = run_render(job1.id)
        assert stats1["segments_total"] == 3
        assert stats1["segments_rendered"] == 3 and stats1["segments_reused"] == 0

        db.refresh(job1)
        assert job1.status == "done" and job1.output_key
        # drift check: total ~= intro + body(sum of per-step TTS) + outro
        spec = vp.edit_spec_json
        expected = (spec["intro"]["duration_ms"] + stats1["expected_body_ms"]
                    + spec["outro"]["duration_ms"]) / 1000.0
        actual = _probe_s(job1.output_key)
        assert abs(actual - expected) < 0.7, f"drift: actual={actual} expected={expected}"

        # ---- edit ONE segment's script, then regenerate ----
        new_spec = {**vp.edit_spec_json}
        new_spec["segments"] = [dict(s) for s in new_spec["segments"]]
        new_spec["segments"][1]["words"] = ["Completely", "different", "narration", "now."]
        new_spec["segments"][1]["removed"] = []
        vp.edit_spec_json = mark_dirty(vp.edit_spec_json, new_spec)
        db.commit()

        job2 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job2)
        db.commit()
        db.refresh(job2)
        stats2 = run_render(job2.id)
        # E6: only the changed segment re-renders; the other two are reused from cache
        assert stats2["segments_rendered"] == 1, stats2
        assert stats2["segments_reused"] == 2, stats2
    finally:
        db.close()
