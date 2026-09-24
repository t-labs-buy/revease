"""A scene clip's footage starts at t=0 even when the input seek lands a
fraction of a frame late — otherwise the backdrop overlay shows alone for the
first frame (a visible flash at every scene change)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from worker.pipeline.render import FPS, _footage_head

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _first_frame_mean(src: Path, ss: str, vf_head: str) -> float:
    """Mean grey level of the first output frame when `src` (seeked to `ss`) is
    laid over a plain white backdrop: ~255 means the backdrop showed alone."""
    fc = (f"[0:v]{vf_head}scale=64:36[main];"
          f"color=c=white:s=64x36:r={FPS}[bg];[bg][main]overlay=0:0")
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", ss, "-t", "0.5", "-i", str(src),
         "-filter_complex", fc, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    return sum(raw) / len(raw)


def test_late_first_frame_no_longer_flashes_the_backdrop(tmp_path: Path):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=64x36:rate={FPS}:duration=2",
         "-pix_fmt", "yuv420p", str(src)], check=True,
    )
    # seek between two source frames: the first decoded frame is ~0.023 s late
    late = "0.51"
    assert _first_frame_mean(src, late, "") > 250          # the bug: backdrop only
    assert _first_frame_mean(src, late, _footage_head() + ",") < 200  # fixed: footage at t=0
