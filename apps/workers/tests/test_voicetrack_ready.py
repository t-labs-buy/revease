"""The voice preview track must become visible only once it is complete and its
pacing timeline is saved. The API treats the wav's existence as "ready", so a
wav written in place used to be picked up half-built and without a timeline —
the editor then played the voice unretimed, with lines under the wrong scenes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.editspec import build_edit_spec, voice_timeline_key, voice_track_key
from app.models import Project, VideoProject
from app.storage import store
from worker.pipeline import voicetrack
from worker.pipeline.render import StepAudio

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

GRAPH = {
    "version": 1, "title": "Voice", "steps": [
        {"id": "s1", "action": "click", "target": "A", "narration": "First line.",
         "t_start": 0.0, "t_end": 2.0, "bbox": None},
        {"id": "s2", "action": "click", "target": "B", "narration": "Second line.",
         "t_start": 2.0, "t_end": 4.0, "bbox": None},
    ],
}


def _silent_wav(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds:.2f}", str(path)], check=True,
    )


def test_track_appears_only_after_its_timeline(monkeypatch, tmp_path: Path):
    db = SessionLocal()
    try:
        p = Project(name="voice")
        db.add(p)
        db.commit()
        db.refresh(p)
        spec = build_edit_spec(GRAPH, {"w": 1280, "h": 720})
        db.add(VideoProject(project_id=p.id, graph_version=1, edit_spec_json=spec))
        db.commit()
        pid = p.id
    finally:
        db.close()

    # stand in for TTS: every scene gets a 1 s silent clip
    def fake_audio(s, *, work, **_kw):
        clip = tmp_path / f"{s['step_id']}.wav"
        _silent_wav(clip, 1.0)
        return StepAudio(str(clip), 1000, False, 0)

    monkeypatch.setattr(voicetrack, "compute_step_audio", fake_audio)

    out = store.local_path(voice_track_key(pid, "af_sarah", 1.0, spec))
    tpath = store.local_path(voice_timeline_key(pid, "af_sarah", 1.0, spec))
    seen: dict[str, bool] = {}
    real_run = subprocess.run

    def spy_run(cmd, *a, **kw):
        # while ffmpeg builds the track, the published wav must not exist yet
        seen["wav_during_build"] = out.exists()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(voicetrack.subprocess, "run", spy_run)

    res = voicetrack.build_voice_track(pid, "af_sarah", 1.0)
    assert "error" not in res
    assert seen["wav_during_build"] is False
    assert out.exists() and tpath.exists()
    assert not list(out.parent.glob("*.part.wav"))  # scratch file cleaned up

    # a second build is a cache hit — and only because BOTH files are present
    assert voicetrack.build_voice_track(pid, "af_sarah", 1.0).get("cached") is True
    tpath.unlink()
    assert voicetrack.build_voice_track(pid, "af_sarah", 1.0).get("cached") is None
    assert tpath.exists()
