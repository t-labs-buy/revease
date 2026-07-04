import shutil
import subprocess

import pytest

from app.db import SessionLocal
from app.models import AutoEditJob, CaptureSession, MediaAsset, Project
from app.storage import store
from worker.pipeline import autoedit
from worker.pipeline.autoedit_job import run_autoedit

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_video(path):
    """6s: 0-2 active+sound, 2-4 static+silence, 4-6 active+sound."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent
    parts = []
    for i, (src, aud) in enumerate(
        [
            ("testsrc=size=640x360:rate=15:duration=2", "sine=frequency=440:duration=2"),
            ("color=c=gray:size=640x360:rate=15:duration=2", "anullsrc=r=44100:cl=stereo:duration=2"),
            ("testsrc=size=640x360:rate=15:duration=2", "sine=frequency=440:duration=2"),
        ]
    ):
        p = tmp / f"part{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i", aud,
             "-shortest", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", str(p)],
            capture_output=True, check=True,
        )
        parts.append(p)
    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
         "-c:v", "libx264", "-c:a", "aac", str(path)],
        capture_output=True, check=True,
    )


def test_analyze_detects_silence_and_speeds_it_up():
    video = store.local_path("test/ae_src.mp4")
    _make_video(video)
    a = autoedit.analyze(video)
    assert a.duration > 5
    # at least one segment should be sped up (the silent middle)
    assert any(s.speed > 1.0 for s in a.segments)


def test_srt_retimes_words_to_output_clock():
    from worker.pipeline.autoedit import Seg, build_srt

    # segment 0: 0-2s normal (1x); segment 1: 2-6s silent sped 4x -> out 1s
    segs = [Seg(0.0, 2.0, 1.0), Seg(2.0, 6.0, 4.0)]
    words = [
        {"w": "Hello", "t_start": 0.5, "t_end": 0.9},
        {"w": "world.", "t_start": 1.0, "t_end": 1.4},
        {"w": "Later.", "t_start": 3.0, "t_end": 3.4},  # inside sped segment
    ]
    srt = build_srt(words, segs)
    assert "Hello world." in srt
    assert "-->" in srt
    # "Later." at orig 3.0 maps to out 2.0 + (3.0-2.0)/4 = 2.25s -> "00:00:02,250"
    assert "00:00:02,2" in srt


def test_aggressiveness_presets_change_speed():
    from worker.pipeline import autoedit

    video = store.local_path("test/ae_src.mp4")
    _make_video(video)
    gentle = autoedit.analyze(video, preset="gentle")
    aggressive = autoedit.analyze(video, preset="aggressive")
    gmax = max((s.speed for s in gentle.segments), default=1)
    amax = max((s.speed for s in aggressive.segments), default=1)
    assert amax >= gmax  # aggressive speeds silent parts more


def test_freeze_detection_speeds_static_section():
    # moving+sound / STATIC+sound / moving+sound -> middle is frozen but not silent
    video = store.local_path("test/ae_freeze.mp4")
    video.parent.mkdir(parents=True, exist_ok=True)
    tmp = video.parent
    parts = []
    for i, src in enumerate(
        ["testsrc=size=640x360:rate=15:duration=2",
         "color=c=gray:size=640x360:rate=15:duration=3",
         "testsrc=size=640x360:rate=15:duration=2"]
    ):
        p = tmp / f"fz{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-f", "lavfi",
             "-i", "sine=frequency=440:duration=3", "-shortest", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "44100", str(p)],
            capture_output=True, check=True,
        )
        parts.append(p)
    listf = tmp / "fzlist.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
         "-c:v", "libx264", "-c:a", "aac", str(video)],
        capture_output=True, check=True,
    )
    freezes = autoedit.detect_freezes(video, autoedit.probe_duration(video))
    assert len(freezes) >= 1  # the static middle is detected


def test_autoedit_job_produces_shorter_video():
    db = SessionLocal()
    try:
        p = Project(name="ae")
        db.add(p)
        db.commit()
        db.refresh(p)
        sess = CaptureSession(project_id=p.id, source_type="upload", telemetry="absent", status="ready")
        db.add(sess)
        db.commit()
        db.refresh(sess)
        key = f"sessions/{sess.id}/raw_video.mp4"
        _make_video(store.local_path(key))
        db.add(MediaAsset(session_id=sess.id, kind="raw_video", storage_key=key))
        job = AutoEditJob(project_id=p.id, status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)

        stats = run_autoedit(job.id)
        assert stats["sped_up"] >= 1
        # sped-up silence => output shorter than source
        assert stats["output_duration_ms"] < stats["source_duration_ms"]
        db.refresh(job)
        assert job.status == "done" and job.output_key
    finally:
        db.close()
