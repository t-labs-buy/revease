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
    # cards are opt-in for new projects; this test exercises them on purpose
    spec["intro"]["enabled"] = True
    spec["outro"]["enabled"] = True
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


def _png(key: str, color=(255, 255, 255, 0), size=(200, 100)) -> str:
    from PIL import Image

    out = store.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", size, color)
    im.paste((30, 143, 142, 255), (40, 20, 160, 80))
    im.save(out)
    return key


def _mean_volume(key: str, start: float, dur: float) -> float:
    err = subprocess.run(
        ["ffmpeg", "-ss", f"{start}", "-t", f"{dur}", "-i", str(store.local_path(key)),
         "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True,
    ).stderr
    line = next(ln for ln in err.splitlines() if "mean_volume" in ln)
    return float(line.split("mean_volume:")[1].split()[0])


def test_media_inserts_overlays_and_music_never_rerender_scenes():
    """Media tab: a title card at the start, an image after scene 1, a logo
    overlay and a music bed. Total = inserts + body (inserts sit outside the
    scene timeline), and moving the logo or changing the music re-renders zero
    scenes — overlays and music live in the concat/mix passes only."""
    db = SessionLocal()
    try:
        vp = _setup(db)
        spec = {**vp.edit_spec_json}
        spec["intro"] = {**spec["intro"], "enabled": False}
        spec["outro"] = {**spec["outro"], "enabled": False}
        logo = _png(f"projects/{vp.project_id}/logo.png")
        still = _png(f"projects/{vp.project_id}/still.png", color=(200, 30, 30, 255))
        tone = f"projects/{vp.project_id}/music.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                        str(store.local_path(tone))], capture_output=True, check=True)
        spec["inserts"] = [
            {"id": "t1", "type": "title", "title": "Welcome", "position": "start", "duration_ms": 1000},
            {"id": "i1", "type": "image", "media_key": still, "position": "after:s1", "duration_ms": 800},
            {"id": "gone", "type": "image", "media_key": "projects/x/missing.png", "position": "end",
             "duration_ms": 900},  # a deleted asset is skipped, not fatal
        ]
        spec["overlays"] = [{"id": "o1", "type": "image", "media_key": logo, "x": 0.8, "y": 0.05,
                             "w": 0.15, "h": 0.1, "range": "all", "opacity": 0.9}]
        spec["music"] = {"enabled": True, "storage_key": tone, "gain_db": -12, "duck": True}
        vp.edit_spec_json = spec
        db.commit()

        job1 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job1)
        db.commit()
        stats1 = run_render(job1.id)
        assert stats1["inserts"] == 2 and stats1["overlays"] == 1 and stats1["music"]
        db.refresh(job1)
        expected = (1000 + 800 + stats1["expected_body_ms"]) / 1000
        assert abs(_probe_s(job1.output_key) - expected) < 0.7
        assert _mean_volume(job1.output_key, 0.1, 0.8) > -50  # the music bed is audible

        # move the logo + turn the music down: every scene comes from cache
        spec2 = {**vp.edit_spec_json}
        spec2["overlays"] = [{**spec2["overlays"][0], "x": 0.05, "range": {"start_ms": 0, "end_ms": 1500}}]
        spec2["music"] = {**spec2["music"], "gain_db": -24}
        vp.edit_spec_json = mark_dirty(vp.edit_spec_json, spec2)
        db.commit()
        job2 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job2)
        db.commit()
        stats2 = run_render(job2.id)
        assert stats2["segments_rendered"] == 0 and stats2["segments_reused"] == 3, stats2
        db.refresh(job2)
        assert job2.output_key != job1.output_key
    finally:
        db.close()


def test_pause_marker_adds_silence_and_rerenders_only_its_scene():
    """A `[pause:N]` token in one scene's script lengthens that scene by N
    seconds of silence and re-renders it alone — the other scenes' audio file
    names (and so their clip hashes) are untouched."""
    db = SessionLocal()
    try:
        vp = _setup(db)
        spec = {**vp.edit_spec_json}
        spec["intro"] = {**spec["intro"], "enabled": False}
        spec["outro"] = {**spec["outro"], "enabled": False}
        vp.edit_spec_json = spec
        db.commit()

        job1 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job1)
        db.commit()
        db.refresh(job1)
        stats1 = run_render(job1.id)
        assert stats1["segments_rendered"] == 3

        new_spec = {**vp.edit_spec_json}
        new_spec["segments"] = [dict(s) for s in new_spec["segments"]]
        words = list(new_spec["segments"][1]["words"])
        new_spec["segments"][1]["words"] = words[:2] + ["[pause:1.5]"] + words[2:]
        vp.edit_spec_json = mark_dirty(vp.edit_spec_json, new_spec)
        db.commit()

        job2 = RenderJob(video_project_id=vp.id, status="pending")
        db.add(job2)
        db.commit()
        db.refresh(job2)
        stats2 = run_render(job2.id)
        assert stats2["segments_rendered"] == 1 and stats2["segments_reused"] == 2, stats2
        db.refresh(job1)
        db.refresh(job2)
        # the offline TTS stub sizes a clip by word count with a floor, so the
        # split halves may each hit the floor: the scene grows by AT LEAST the pause
        assert _probe_s(job2.output_key) - _probe_s(job1.output_key) >= 1.4
    finally:
        db.close()
