"""Every clip fed to the final concat must share one frame rate / mp4 time base
(ffmpeg's concat demuxer does not rescale between differing time bases)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from worker.pipeline import render
from worker.pipeline.render import BG_PRESETS, FPS, MP4_TIMESCALE, _bg_source, _has_audio


def _probe(path: Path, stream: str, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", f"stream={entries}",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()


def _mean_volume_db(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    for line in out.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    return -999.0


def test_media_card_keeps_video_soundtrack_and_normalizes_timing(tmp_path, monkeypatch):
    # a 24 fps clip with a 440 Hz tone, and one with no audio at all
    tone = tmp_path / "tone.mp4"
    silent = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "1",
         "-c:v", "libx264", "-c:a", "aac", str(tone)], check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24",
         "-t", "1", "-c:v", "libx264", str(silent)], check=True,
    )
    assert _has_audio(tone) and not _has_audio(silent)
    monkeypatch.setattr(render.store, "local_path", lambda key: tmp_path / key)

    with_sound, _ = render._render_media_card("tone.mp4", "video", 1000, (320, 180), tmp_path, "intro")
    no_sound, _ = render._render_media_card("silent.mp4", "video", 1000, (320, 180), tmp_path, "outro")

    # the uploaded soundtrack is audible; a silent source still gets a (silent) track
    assert _mean_volume_db(with_sound) > -30
    assert _probe(no_sound, "a", "codec_type") == "audio"
    assert _mean_volume_db(no_sound) < -80
    # both are normalized to FPS with the shared time base, whatever the upload was
    for clip in (with_sound, no_sound):
        assert _probe(clip, "v", "r_frame_rate,time_base") == f"{FPS}/1,1/{MP4_TIMESCALE}"


def test_backdrop_source_is_pinned_to_fps():
    # lavfi sources default to 25 fps and `overlay` inherits the rate of its
    # first input — the backdrop — which silently made backed scenes 25 fps.
    for style in [None, *BG_PRESETS]:
        assert f":r={FPS}" in _bg_source(style, (1920, 1080)), style


def test_mp4_timescale_matches_fps():
    assert MP4_TIMESCALE == FPS * 512
