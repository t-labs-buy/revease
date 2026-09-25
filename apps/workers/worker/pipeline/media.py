"""FFmpeg media processing: scene-change keyframe extraction (capped ~1 fps) and
audio demux. On failure the full command + stderr are logged (master §5) and the
pipeline continues with whatever media it has."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.config import get_settings

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


def parse_progress_line(line: str) -> float | None:
    """Seconds of output written, from an `ffmpeg -progress` key=value line."""
    key, _, val = line.strip().partition("=")
    if key in ("out_time_us", "out_time_ms"):  # both are microseconds (ffmpeg quirk)
        try:
            return max(0.0, int(val) / 1_000_000)
        except ValueError:
            return None
    return None


def run_with_progress(
    cmd: list[str],
    duration_s: float,
    on_progress: Callable[[float, float], None] | None = None,
    timeout_s: float | None = None,
) -> None:
    """Run ffmpeg with `-progress pipe:1`, calling on_progress(fraction, seconds_done).
    stderr goes to a temp file (never a pipe: a chatty ffmpeg would fill it and
    deadlock while we read stdout). Raises FFmpegError on failure or timeout,
    and kills the process on the way out so no orphan keeps burning CPU."""
    full = cmd[:1] + ["-nostats", "-progress", "pipe:1"] + cmd[1:]
    log.info("ffmpeg: %s", " ".join(full))
    deadline = time.monotonic() + timeout_s if timeout_s else None
    with tempfile.TemporaryFile(mode="w+") as err:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                done = parse_progress_line(line)
                if done is not None and on_progress and duration_s > 0:
                    on_progress(min(1.0, done / duration_s), done)
                if deadline and time.monotonic() > deadline:
                    raise FFmpegError(f"ffmpeg timed out after {timeout_s:.0f}s")
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if rc != 0:
            err.seek(0)
            tail = err.read()[-4000:]
            log.error("FFmpeg failed (%s):\ncmd: %s\nstderr:\n%s", rc, " ".join(full), tail)
            raise FFmpegError(tail.strip().splitlines()[-1] if tail.strip() else "ffmpeg failed")


PROXY_HEIGHT = 540


def _proxy_args(has_a: bool, fps: int, threads: int) -> list[str]:
    """Small H.264 for browser preview/scrubbing: 540p, lower quality, light
    audio. Roughly a fifth of the full file, so the editor loads fast."""
    args = ["-vf", f"scale=-2:{PROXY_HEIGHT}", "-fps_mode", "cfr", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
            "-threads", str(threads)]
    args += ["-c:a", "aac", "-b:a", "64k", "-ac", "1"] if has_a else ["-an"]
    return args + ["-movflags", "+faststart"]


def make_proxy(
    src: Path,
    out_mp4: Path,
    *,
    duration_s: float = 0.0,
    on_progress: Callable[[float, float], None] | None = None,
) -> Path:
    """Preview proxy from an already-good MP4 (when no normalize pass runs)."""
    s = get_settings()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_mp4.with_name(out_mp4.stem + ".part.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(src), *_proxy_args(has_audio(src), s.media_normalize_fps, s.media_threads), str(tmp)]
    try:
        run_with_progress(cmd, duration_s or _container_duration(src), on_progress,
                          timeout_s=s.media_normalize_timeout_s)
        tmp.replace(out_mp4)
    finally:
        tmp.unlink(missing_ok=True)
    return out_mp4


def normalize_video(
    src: Path,
    out_mp4: Path,
    *,
    duration_s: float = 0.0,
    on_progress: Callable[[float, float], None] | None = None,
    proxy_out: Path | None = None,
) -> Path | None:
    """Transcode a recording/upload into a faststart MP4 that carries a real
    duration header. Browser recordings are header-less WebM (MediaRecorder):
    no duration, so the browser can't seek them and ffprobe reads 0 — which
    breaks the trim UI, the preview timeline, and auto-edit. Returns the new
    path, or None when the source is already a well-formed MP4 (skip re-encode).

    Bounded on purpose: a constant output frame rate (browser WebM reports
    1000 fps), a thread cap, a timeout, and a write to a temp name that is
    renamed only on success — so a killed or duplicated run can never leave a
    half-written source.mp4 that later stages would trust."""
    if src.suffix.lower() == ".mp4" and _container_duration(src) > 0:
        return None
    s = get_settings()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_mp4.with_name(out_mp4.stem + ".part.mp4")
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", str(src),
           "-fps_mode", "cfr", "-r", str(s.media_normalize_fps),
           "-c:v", "libx264", "-preset", s.media_normalize_preset, "-pix_fmt", "yuv420p",
           "-threads", str(s.media_threads)]
    has_a = has_audio(src)
    cmd += ["-c:a", "aac", "-ar", "44100"] if has_a else ["-an"]
    cmd += ["-movflags", "+faststart", str(tmp)]
    # The preview proxy rides the same pass: decoding the browser's VP9 is the
    # expensive part, so a second output costs far less than a second run.
    proxy_tmp = proxy_out.with_name(proxy_out.stem + ".part.mp4") if proxy_out else None
    if proxy_tmp is not None:
        proxy_tmp.parent.mkdir(parents=True, exist_ok=True)
        cmd += [*_proxy_args(has_a, s.media_normalize_fps, s.media_threads), str(proxy_tmp)]
    try:
        run_with_progress(cmd, duration_s or _container_duration(src), on_progress,
                          timeout_s=s.media_normalize_timeout_s)
        tmp.replace(out_mp4)
        if proxy_tmp is not None and proxy_out is not None:
            proxy_tmp.replace(proxy_out)
    finally:
        tmp.unlink(missing_ok=True)
        if proxy_tmp is not None:
            proxy_tmp.unlink(missing_ok=True)
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
    _run(["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
          "-threads", str(get_settings().media_threads), str(out_wav)])
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
        "ffmpeg", "-y", "-threads", str(get_settings().media_threads), "-i", str(video_path),
        # -fps_mode replaced -vsync in ffmpeg 5.1 and -vsync was removed in 7; the
        # Debian image ships 5.1+, so the new spelling works everywhere we run.
        "-vf", vf, "-fps_mode", "vfr", "-q:v", "3", "-frames:v", str(max_frames),
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
