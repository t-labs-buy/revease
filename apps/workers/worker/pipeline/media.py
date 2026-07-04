"""FFmpeg media processing: scene-change keyframe extraction (capped ~1 fps) and
audio demux. On failure the full command + stderr are logged (master §5) and the
pipeline continues with whatever media it has."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("refract.pipeline.media")


@dataclass
class Keyframe:
    t: float
    path: Path


class FFmpegError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    log.info("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Log the full command + stderr, then raise a typed error.
        log.error("FFmpeg failed (%s):\ncmd: %s\nstderr:\n%s", proc.returncode, " ".join(cmd), proc.stderr)
        raise FFmpegError(proc.stderr.strip().splitlines()[-1] if proc.stderr else "ffmpeg failed")
    return proc


def _container_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def normalize_video(src: Path, out_mp4: Path) -> Path | None:
    """Transcode a recording/upload into a faststart MP4 that carries a real
    duration header. Browser recordings are header-less WebM (MediaRecorder):
    no duration, so the browser can't seek them and ffprobe reads 0 — which
    breaks the trim UI, the preview timeline, and auto-edit. Returns the new
    path, or None when the source is already a well-formed MP4 (skip re-encode)."""
    if src.suffix.lower() == ".mp4" and _container_duration(src) > 0:
        return None
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", str(src),
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-ar", "44100"] if has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", str(out_mp4)]
    _run(cmd)
    return out_mp4


def has_audio(video_path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True,
        )
        return bool(proc.stdout.strip())
    except FileNotFoundError:
        return False


def demux_audio(video_path: Path, out_wav: Path) -> Path | None:
    """Extract mono 16 kHz wav (Whisper-friendly). Returns None if no audio track."""
    if not has_audio(video_path):
        log.info("no audio track in %s", video_path)
        return None
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(out_wav)])
    return out_wav


def extract_keyframes(
    video_path: Path, out_dir: Path, fps_cap: float = 1.0, max_frames: int = 600
) -> list[Keyframe]:
    """Adaptive keyframes: scene changes plus a hard time cap of ~fps_cap frames/sec
    (default 1 fps). `fps=fps_cap` samples on a fixed clock; scene detection adds
    extra frames at cuts. Emits frame_%04d.jpg + showinfo timestamps."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # fps=<cap> samples on a fixed clock (~cap frames/sec) — predictable, never
    # explodes. `-frames:v max_frames` is a hard backstop for very long videos.
    vf = f"fps={fps_cap},showinfo"
    proc = _run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf, "-vsync", "vfr", "-q:v", "3", "-frames:v", str(max_frames),
        str(out_dir / "frame_%04d.jpg"),
    ])
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    frames = sorted(out_dir.glob("frame_*.jpg"))
    keyframes: list[Keyframe] = []
    for i, fp in enumerate(frames):
        t = times[i] if i < len(times) else float(i)
        keyframes.append(Keyframe(t=t, path=fp))
    log.info("extracted %d keyframes from %s (cap %d)", len(keyframes), video_path, max_frames)
    return keyframes
