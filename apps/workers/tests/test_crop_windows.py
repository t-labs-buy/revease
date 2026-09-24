"""A crop applies exactly inside its own time window, mid-scene included — the
render reframes the footage the way the editor previews it, instead of cropping
a whole scene because the crop's window touched it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from worker.pipeline.render import (
    _crop_filter,
    _crop_windows_for_segment,
    _fit_filter,
    _reframe_graph,
)

CORNER = {"enabled": True, "x": 0.0, "y": 0.0, "w": 0.25, "h": 0.25, "start_ms": 5000, "end_ms": 6000}
SCENE = {"source_start_ms": 4000, "source_end_ms": 7000}  # 3 s scene; crop covers 1 s..2 s of it


def test_window_is_clipped_to_the_scene_and_made_relative():
    assert _crop_windows_for_segment([CORNER], SCENE) == [(CORNER, 1.0, 2.0)]
    early = {**CORNER, "start_ms": 1000, "end_ms": 5500}  # starts before the scene
    assert _crop_windows_for_segment([early], SCENE) == [(early, 0.0, 1.5)]


def test_untouched_and_windowless_crops():
    later = {**CORNER, "start_ms": 9000, "end_ms": 9500}
    assert _crop_windows_for_segment([later], SCENE) == []
    whole = {k: v for k, v in CORNER.items() if k not in ("start_ms", "end_ms")}
    assert _crop_windows_for_segment([whole], SCENE) == [(whole, 0.0, 3.0)]
    assert _crop_windows_for_segment([{**CORNER, "enabled": False}], SCENE) == []


def test_full_scene_crop_keeps_the_plain_chain():
    whole = {k: v for k, v in CORNER.items() if k not in ("start_ms", "end_ms")}
    g = _reframe_graph([(whole, 0.0, 3.0)], 3.0, 320, 180)
    assert g == f"{_crop_filter(whole)},{_fit_filter(whole, 320, 180)}"
    assert _reframe_graph([], 3.0, 320, 180) == _fit_filter(None, 320, 180)


def test_partial_window_switches_by_time():
    g = _reframe_graph([(CORNER, 1.0, 2.0)], 3.0, 320, 180)
    assert g.startswith("split=2[rf0][rf1];")
    assert "enable='between(t,1.000,2.000)'" in g
    assert not g.endswith("]")  # unlabelled tail: more filters can follow with a comma


def test_window_reaching_the_scene_end_stays_on_through_the_hold():
    # crop starts 2.293 s into a 2.36 s scene and runs to its end: the enable
    # window must extend past the scene so the re-timed last frame (which can
    # round to 2.367 s) and the held frames after it stay cropped
    late = {**CORNER, "start_ms": 6293, "end_ms": 9000}
    win = _crop_windows_for_segment([late], {"source_start_ms": 4000, "source_end_ms": 6360})
    assert win == [(late, 2.293, 2.36)]
    g = _reframe_graph(win, 2.36, 320, 180)
    assert "enable='between(t,2.293,3.360)'" in g


def _frames(src: Path, vf: str, w: int, h: int) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_ffmpeg_output_is_uncropped_then_cropped(tmp_path: Path):
    w, h, fps = 320, 180, 10
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate={fps}:duration=3",
         "-pix_fmt", "yuv420p", str(src)], check=True,
    )
    n = w * h * 3
    got = _frames(src, _reframe_graph([(CORNER, 1.0, 2.0)], 3.0, w, h), w, h)
    plain = _frames(src, _fit_filter(None, w, h), w, h)
    cropped = _frames(src, f"{_crop_filter(CORNER)},{_fit_filter(CORNER, w, h)}", w, h)
    assert len(got) == len(plain) == len(cropped) == 30 * n

    def frame(buf: bytes, i: int) -> bytes:
        return buf[i * n:(i + 1) * n]

    def diff(a: bytes, b: bytes) -> float:
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

    # 0.5 s: before the window -> the full frame; 1.5 s: inside -> the corner blown up
    assert diff(frame(got, 5), frame(plain, 5)) < 2.0
    assert diff(frame(got, 15), frame(cropped, 15)) < 2.0
    assert diff(frame(got, 15), frame(plain, 15)) > 20.0  # and those two really differ
    # 2.5 s: after the window -> full frame again
    assert diff(frame(got, 25), frame(plain, 25)) < 2.0
