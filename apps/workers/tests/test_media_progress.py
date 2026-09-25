"""Long-video handling: progress parsing, the bounded normalize, the progress
reporter, and the pipeline's refusal to start a duplicate run."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import CaptureSession, Job, Project
from worker.pipeline.media import normalize_video, parse_progress_line
from worker.pipeline.progress import Reporter, fmt_clock
from worker.pipeline.run import run_pipeline

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_parse_progress_line():
    assert parse_progress_line("out_time_us=12500000\n") == 12.5
    assert parse_progress_line("out_time_ms=3000000") == 3.0  # also microseconds
    assert parse_progress_line("frame=120") is None
    assert parse_progress_line("out_time_us=N/A") is None


def test_fmt_clock():
    assert fmt_clock(75) == "01:15" and fmt_clock(3725) == "1:02:05" and fmt_clock(-3) == "00:00"


@needs_ffmpeg
def test_normalize_reports_progress_caps_fps_and_leaves_no_partial(tmp_path):
    src = tmp_path / "rec.webm"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=60:duration=3",
                    "-c:v", "libvpx-vp9", "-deadline", "realtime", str(src)], capture_output=True, check=True)
    out = tmp_path / "source.mp4"
    seen: list[float] = []
    assert normalize_video(src, out, duration_s=3.0, on_progress=lambda f, _s: seen.append(f)) == out
    assert out.exists() and not (tmp_path / "source.part.mp4").exists()
    assert seen and seen[-1] > 0.8 and seen == sorted(seen)
    fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
    assert fps.stdout.strip() == "30/1"  # 60 fps source bounded to 30


def _session_with_running_media(heartbeat_age_s: float) -> str:
    db = SessionLocal()
    p = Project(name="dup")
    db.add(p)
    db.commit()
    sess = CaptureSession(project_id=p.id, source_type="recorder", status="processing", pipeline_token="tok-1")
    db.add(sess)
    db.commit()
    job = Job(session_id=sess.id, stage="media", version=1, status="running", attempts=1)
    db.add(job)
    db.commit()
    job.updated_at = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_s)
    db.commit()
    sid = sess.id
    db.close()
    return sid


def test_redelivered_duplicate_is_dropped_while_run_is_live():
    sid = _session_with_running_media(heartbeat_age_s=5)
    r = run_pipeline(sid, "tok-1")
    assert r["skipped"] == "already running" and r["stage"] == "media"
    assert run_pipeline(sid, None)["skipped"] == "already running"  # legacy message, no token


def test_new_request_waits_for_the_live_run():
    sid = _session_with_running_media(heartbeat_age_s=5)
    assert run_pipeline(sid, "tok-2")["deferred"] is True


def test_stale_run_is_taken_over():
    sid = _session_with_running_media(heartbeat_age_s=3600)
    r = run_pipeline(sid, "tok-3")
    assert "skipped" not in r and "deferred" not in r
    db = SessionLocal()
    assert db.get(CaptureSession, sid).pipeline_token == "tok-3"
    db.close()


def test_reporter_scales_and_throttles():
    db = SessionLocal()
    p = Project(name="rep")
    db.add(p)
    db.commit()
    sess = CaptureSession(project_id=p.id, source_type="upload")
    db.add(sess)
    db.commit()
    job = Job(session_id=sess.id, stage="media", version=1, status="running")
    db.add(job)
    db.commit()
    jid = job.id
    db.close()

    rep = Reporter(Job, jid, min_interval=60).sub(0.0, 0.8)
    rep(0.5, "Converting video")  # message change -> written
    rep(0.9)  # throttled (same message, inside the interval)
    db = SessionLocal()
    j = db.scalar(select(Job).where(Job.id == jid))
    assert j.progress == 0.4 and j.message == "Converting video"
    db.close()


def test_deferred_request_keeps_waiting_past_the_error_retry_limit(monkeypatch):
    """A request waiting on a live run must not give up after the 3 error retries."""
    from celery.exceptions import Retry

    from worker import tasks

    monkeypatch.setattr("worker.pipeline.run.run_pipeline", lambda sid, tok: {"deferred": True})
    task = tasks.run_understanding
    task.push_request(retries=50, id="t1", delivery_info={}, called_directly=False)
    try:
        with pytest.raises(Retry):
            task("sid", "tok")
    finally:
        task.pop_request()
    assert tasks.DEFER_MAX_WAITS * tasks.DEFER_COUNTDOWN_S >= 24 * 3600
