"""Every clip fed to the final concat must share one frame rate / mp4 time base
(ffmpeg's concat demuxer does not rescale between differing time bases)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from worker.pipeline import render
from worker.pipeline.render import (
    AUDIO_CHANNELS,
    AUDIO_RATE,
    BG_PRESETS,
    FPS,
    MP4_TIMESCALE,
    _bg_source,
    _has_audio,
)


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
    # media is read through store.fetch (the storage contract: S3 downloads first)
    monkeypatch.setattr(render.store, "fetch", lambda key: (tmp_path / key) if (tmp_path / key).exists() else None)

    with_sound, _ = render._render_media_card("tone.mp4", "video", 1000, (320, 180), tmp_path, "intro")
    no_sound, _ = render._render_media_card("silent.mp4", "video", 1000, (320, 180), tmp_path, "outro")

    # the uploaded soundtrack is audible; a silent source still gets a (silent) track
    assert _mean_volume_db(with_sound) > -30
    assert _probe(no_sound, "a", "codec_type") == "audio"
    assert _mean_volume_db(no_sound) < -80
    # both are normalized to FPS with the shared time base, whatever the upload was
    for clip in (with_sound, no_sound):
        assert _probe(clip, "v", "r_frame_rate,time_base") == f"{FPS}/1,1/{MP4_TIMESCALE}"
        # ...and to the scene clips' audio layout: a stereo insert between mono
        # scenes left every later scene 3 dB down with noise in the pauses
        assert _probe(clip, "a", "sample_rate,channels") == f"{AUDIO_RATE},{AUDIO_CHANNELS}"


def test_image_insert_matches_scene_audio_layout(tmp_path, monkeypatch):
    # an image insert gets a synthetic silent track — it must be mono like the scenes
    png = tmp_path / "logo.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64",
         "-frames:v", "1", str(png)], check=True,
    )
    monkeypatch.setattr(render.store, "local_path", lambda key: tmp_path / key)
    monkeypatch.setattr(render.store, "fetch", lambda key: (tmp_path / key) if (tmp_path / key).exists() else None)
    clip, dur = render._render_media_card("logo.png", "image", 1500, (320, 180), tmp_path, "ins_x")
    assert dur == 1500
    assert _probe(clip, "a", "sample_rate,channels") == f"{AUDIO_RATE},{AUDIO_CHANNELS}"
    assert _mean_volume_db(clip) < -80


def _aac_clip(path: Path, seconds: float, tone: bool) -> Path:
    """A clip whose length is not a whole number of AAC frames (1024 samples)."""
    audio = f"sine=frequency=440:sample_rate={AUDIO_RATE}" if tone else f"anullsrc=r={AUDIO_RATE}:cl=mono"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s=64x64:r={FPS}",
         "-f", "lavfi", "-i", audio, "-t", f"{seconds:.3f}", "-c:v", "libx264", "-c:a", "aac",
         "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CHANNELS), "-video_track_timescale",
         str(MP4_TIMESCALE), str(path)], check=True,
    )
    return path


def _decoded_samples(path: Path) -> int:
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-f", "s16le", "-ac", "1",
         "-ar", str(AUDIO_RATE), "-"], capture_output=True,
    ).stdout
    return len(pcm) // 2


def test_exact_audio_is_the_slot_length_to_the_sample(tmp_path):
    # 1.05 s = 25200 samples = 24.6 AAC frames: the encoded track decodes to a
    # different length than the slot, which is what slid the narration at seams
    clip = _aac_clip(tmp_path / "c.mp4", 1.05, tone=True)
    assert _decoded_samples(clip) != 25200
    wav = render._exact_audio(clip, 1050)
    assert _decoded_samples(wav) == 25200
    assert render._exact_audio(clip, 1050) == wav  # cached next to the clip


def test_join_keeps_narration_on_the_timeline(tmp_path):
    # three awkward-length clips; only the last one has sound. In the joined
    # video that sound must start exactly where the timeline says the third
    # clip does — the old join let it slide ~30 ms later per seam.
    clips = [_aac_clip(tmp_path / f"s{i}.mp4", 1.05, tone=(i == 2)) for i in range(3)]
    vlist = tmp_path / "v.txt"
    vlist.write_text("".join(f"file '{c}'\n" for c in clips))
    alist = tmp_path / "a.txt"
    alist.write_text("".join(f"file '{render._exact_audio(c, 1050)}'\n" for c in clips))
    out = tmp_path / "out.mp4"
    subprocess.run(render._join_cmd(vlist, alist, [], "", 3150, out), check=True, capture_output=True)
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-vn", "-f", "s16le", "-ac", "1",
         "-ar", str(AUDIO_RATE), "-"], capture_output=True,
    ).stdout
    samples = [abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) for i in range(0, len(pcm), 2)]
    first_loud = next(i for i, s in enumerate(samples) if s > 2000)
    assert abs(first_loud / AUDIO_RATE - 2.10) < 0.005, first_loud / AUDIO_RATE


def test_join_maps_audio_after_the_overlay_inputs():
    # overlays are inputs 1..n and reference themselves by index; the PCM audio
    # list must come after them so those indices hold
    cmd = render._join_cmd(Path("v.txt"), Path("a.txt"), ["-loop", "1", "-i", "logo.png"],
                           "[0:v][1:v]overlay[vout]", 1000, Path("o.mp4"))
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    assert "2:a" in cmd and cmd.index("a.txt") > cmd.index("logo.png")


def test_music_without_a_track_means_no_music(tmp_path):
    # the synthesized fallback pad is gone: enabled + no track = silence, and
    # nothing gets written to the work dir
    assert render._music_source({"enabled": True, "storage_key": None}, tmp_path) is None
    assert render._music_source({"enabled": True}, tmp_path) is None
    assert render._music_source(None, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_backdrop_source_is_pinned_to_fps():
    # lavfi sources default to 25 fps and `overlay` inherits the rate of its
    # first input — the backdrop — which silently made backed scenes 25 fps.
    for style in [None, *BG_PRESETS]:
        assert f":r={FPS}" in _bg_source(style, (1920, 1080)), style


def test_mp4_timescale_matches_fps():
    assert MP4_TIMESCALE == FPS * 512
