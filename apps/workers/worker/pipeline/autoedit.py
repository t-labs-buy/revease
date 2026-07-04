"""Auto-edit: turn a raw screen recording into a tighter, focused video WITHOUT
needing click telemetry or narration.

- Silent stretches (via ffmpeg silencedetect) are sped up (they're usually the
  "boring" parts — reading, waiting, idle).
- Active stretches keep normal speed and get a gentle zoom toward where the motion
  is (frame-diff centroid), so the viewer's eye follows the action.

Renders directly from the original footage (re-timed audio kept), so it works for
any uploaded/recorded video.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("refract.pipeline.autoedit")

SPEEDUP = 3.0  # silent regions (usually skippable)
FREEZE_SPEEDUP = 1.6  # static-but-talking regions (tighten, keep voice intelligible)
MIN_SILENCE_S = 1.2  # ignore shorter silences
MIN_FREEZE_S = 1.5  # ignore shorter freezes
MIN_SEG_S = 0.4  # don't emit micro-segments
ZOOM_SCALE = 1.5
FPS = 30


@dataclass
class Seg:
    t_start: float
    t_end: float
    speed: float
    cx: float = 0.5
    cy: float = 0.5
    scale: float = 1.0

    @property
    def src_len(self) -> float:
        return max(0.0, self.t_end - self.t_start)

    @property
    def out_len(self) -> float:
        return self.src_len / self.speed


@dataclass
class Analysis:
    segments: list[Seg] = field(default_factory=list)
    duration: float = 0.0


# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(video: Path) -> float:
    """Playable duration in seconds. MediaRecorder WebM files (from the browser
    recorder) usually carry NO duration in the container header, so the fast
    ffprobe path returns N/A — we then fall back to the stream, then to a full
    decode that always yields the true duration."""
    # 1) container duration (fast; often N/A for streamed WebM)
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(video)])
    try:
        d = float(p.stdout.strip())
        if d > 0:
            return d
    except ValueError:
        pass
    # 2) video stream duration
    p = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=duration", "-of", "csv=p=0", str(video)])
    try:
        d = float(p.stdout.strip())
        if d > 0:
            return d
    except ValueError:
        pass
    # 3) decode the whole stream and read the last timestamp ffmpeg reports —
    #    reliable even when the header lacks a duration.
    p = _run(["ffmpeg", "-i", str(video), "-map", "0:v:0", "-f", "null", "-"])
    times = re.findall(r"time=(\d+):(\d+):([0-9.]+)", p.stderr)
    if times:
        h, m, s = times[-1]
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def probe_dims(video: Path) -> tuple[int, int]:
    p = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height", "-of", "csv=p=0:s=x", str(video)])
    try:
        w, h = p.stdout.strip().split("x")
        return int(w), int(h)
    except (ValueError, IndexError):
        return 1280, 720


def has_audio(video: Path) -> bool:
    p = _run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
              "stream=index", "-of", "csv=p=0", str(video)])
    return bool(p.stdout.strip())


def detect_silences(video: Path, min_silence: float = MIN_SILENCE_S) -> list[tuple[float, float]]:
    """Return [(start,end)] of silent intervals >= min_silence."""
    if not has_audio(video):
        return []
    proc = _run(["ffmpeg", "-i", str(video), "-af", "silencedetect=noise=-30dB:d=%.2f" % min_silence,
                 "-f", "null", "-"])
    log_txt = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", log_txt)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", log_txt)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else s
        if e - s >= min_silence:
            out.append((s, e))
    return out


def detect_freezes(video: Path, duration: float) -> list[tuple[float, float]]:
    """Return [(start,end)] of visually-static intervals >= MIN_FREEZE_S."""
    proc = _run(["ffmpeg", "-i", str(video), "-vf", "freezedetect=n=-60dB:d=%.2f" % MIN_FREEZE_S,
                 "-map", "0:v", "-f", "null", "-"])
    txt = proc.stderr
    starts = [float(m) for m in re.findall(r"freeze_start:\s*([0-9.]+)", txt)]
    ends = [float(m) for m in re.findall(r"freeze_end:\s*([0-9.]+)", txt)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration  # freeze running to EOF has no end line
        if e - s >= MIN_FREEZE_S:
            out.append((s, e))
    return out


def _motion_centroid(video: Path, t0: float, t1: float, dims: tuple[int, int]) -> tuple[float, float, float]:
    """Zoom target from frame-to-frame change within [t0,t1]. Returns (cx,cy,scale)."""
    try:
        import numpy as np
    except Exception:
        return 0.5, 0.5, 1.0
    mid = (t0 + t1) / 2
    a = _grab(video, max(t0, mid - 0.3))
    b = _grab(video, min(t1, mid + 0.3))
    if a is None or b is None:
        return 0.5, 0.5, 1.0
    ga = np.asarray(a.convert("L").resize((160, 90)), dtype="int16")
    gb = np.asarray(b.convert("L").resize((160, 90)), dtype="int16")
    diff = np.abs(ga - gb)
    mask = diff > 18
    if mask.sum() < 40:  # little motion -> no zoom
        return 0.5, 0.5, 1.0
    ys, xs = np.nonzero(mask)
    cx = float(xs.mean()) / 160.0
    cy = float(ys.mean()) / 90.0
    return round(cx, 3), round(cy, 3), ZOOM_SCALE


def _grab(video: Path, t: float):
    from io import BytesIO

    from PIL import Image

    p = subprocess.run(
        ["ffmpeg", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True,
    )
    if p.returncode != 0 or not p.stdout:
        return None
    try:
        return Image.open(BytesIO(p.stdout))
    except Exception:
        return None


def _speed_at(t, silences, freezes, silence_speedup, freeze_speedup) -> float:
    """Silence dominates (skippable), then freeze (tighten), else normal."""
    if any(s <= t < e for s, e in silences):
        return silence_speedup
    if any(s <= t < e for s, e in freezes):
        return freeze_speedup
    return 1.0


# aggressiveness presets: (silence_speedup, freeze_speedup, min_silence_s)
PRESETS = {
    "gentle": (2.0, 1.3, 2.0),
    "balanced": (SPEEDUP, FREEZE_SPEEDUP, MIN_SILENCE_S),
    "aggressive": (4.0, 2.0, 0.8),
}


def analyze(video: Path, *, preset: str = "balanced", zoom: bool = True) -> Analysis:
    silence_speedup, freeze_speedup, min_silence = PRESETS.get(preset, PRESETS["balanced"])
    duration = probe_duration(video)
    dims = probe_dims(video)
    if duration <= 0:
        return Analysis(segments=[Seg(0.0, 0.1, 1.0)], duration=0.0)
    silences = detect_silences(video, min_silence)
    freezes = detect_freezes(video, duration)

    # Split the timeline at every interval boundary, label each slice by speed.
    bounds = {0.0, duration}
    for s, e in silences + freezes:
        bounds.add(max(0.0, min(duration, s)))
        bounds.add(max(0.0, min(duration, e)))
    pts = sorted(bounds)

    raw: list[Seg] = []
    for a, b in zip(pts, pts[1:]):
        if b - a < 1e-3:
            continue
        sp = _speed_at((a + b) / 2, silences, freezes, silence_speedup, freeze_speedup)
        raw.append(Seg(a, b, sp))

    # merge adjacent equal-speed slices, then absorb tiny slices into the previous
    merged: list[Seg] = []
    for seg in raw:
        if merged and abs(merged[-1].speed - seg.speed) < 1e-6:
            merged[-1].t_end = seg.t_end
        else:
            merged.append(seg)
    segs: list[Seg] = []
    for seg in merged:
        if segs and seg.src_len < MIN_SEG_S:
            segs[-1].t_end = seg.t_end
        else:
            segs.append(seg)
    if not segs:
        segs = [Seg(0.0, duration, 1.0)]

    # zoom target for active (normal-speed) segments
    if zoom:
        for seg in segs:
            if seg.speed == 1.0 and seg.src_len >= 0.6:
                seg.cx, seg.cy, seg.scale = _motion_centroid(video, seg.t_start, seg.t_end, dims)
    return Analysis(segments=segs, duration=duration)


# --------------------------------------------------------------------------- #
def _atempo_chain(speed: float) -> str:
    factors: list[float] = []
    s = speed
    while s > 2.0:
        factors.append(2.0)
        s /= 2.0
    factors.append(round(s, 3))
    return ",".join(f"atempo={f}" for f in factors)


def _zoompan_vf(seg: Seg, dims: tuple[int, int]) -> str:
    """Smooth ease-in zoom toward (cx,cy) up to seg.scale over ~1.5s, then hold."""
    w, h = dims
    ease_frames = FPS * min(max(0.3, seg.src_len), 1.5)
    step = max(0.0005, round((seg.scale - 1.0) / ease_frames, 5))
    z = f"min(zoom+{step},{seg.scale})"
    x = f"iw*{seg.cx}-(iw/zoom/2)"
    y = f"ih*{seg.cy}-(ih/zoom/2)"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={FPS}"


def _fmt_ts(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list[dict], segments: list[Seg]) -> str:
    """Re-time transcript words onto the auto-edit output clock (speed-aware)."""
    if not words or not segments:
        return ""
    outs, acc = [], 0.0
    for seg in segments:
        outs.append(acc)
        acc += seg.out_len

    def remap(t: float) -> float:
        for seg, os in zip(segments, outs):
            if seg.t_start <= t < seg.t_end:
                return os + (t - seg.t_start) / seg.speed
        return 0.0 if t < segments[0].t_start else acc

    lines, cur = [], []
    for w in words:
        cur.append(w)
        if str(w.get("w", "")).endswith((".", "?", "!")) or len(cur) >= 8:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)

    entries = []
    for line in lines:
        start = remap(float(line[0]["t_start"]))
        end = remap(float(line[-1]["t_end"]))
        text = " ".join(str(w.get("w", "")).strip() for w in line).strip()
        if text:
            entries.append((start, max(start + 0.6, end), text))
    entries.sort()
    blocks = [
        f"{i}\n{_fmt_ts(s)} --> {_fmt_ts(e)}\n{txt}\n"
        for i, (s, e, txt) in enumerate(entries, start=1)
    ]
    return "\n".join(blocks)


def render(video: Path, analysis: Analysis, out: Path, work: Path, srt_path: Path | None = None) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    dims = probe_dims(video)
    audio = has_audio(video)
    clips: list[Path] = []
    sped = zoomed = 0

    for i, seg in enumerate(analysis.segments):
        if seg.src_len < 0.1:
            continue
        clip = work / f"seg_{i:03d}.mp4"
        if seg.scale > 1.0 and seg.speed == 1.0:
            # smooth zoom (zoompan sets fps + size itself); speed is 1x here
            vf = f"{_zoompan_vf(seg, dims)},format=yuv420p,setsar=1"
        else:
            vf = ",".join([f"setpts=PTS/{seg.speed}", f"fps={FPS}", "format=yuv420p", "setsar=1"])
        cmd = ["ffmpeg", "-y", "-i", str(video), "-ss", f"{seg.t_start:.3f}", "-t",
               f"{seg.src_len:.3f}", "-vf", vf]
        if audio:
            cmd += ["-af", _atempo_chain(seg.speed)]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "44100", str(clip)]
        proc = _run(cmd)
        if proc.returncode != 0:
            log.warning("autoedit seg %d failed: %s", i, proc.stderr[-400:])
            continue
        clips.append(clip)
        sped += int(seg.speed > 1.0)
        zoomed += int(seg.scale > 1.0)

    if not clips:
        raise RuntimeError("no segments rendered")

    listf = work / "concat.txt"
    listf.write_text("".join(f"file '{c}'\n" for c in clips))

    def concat(with_caps: bool) -> subprocess.CompletedProcess[str]:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf)]
        if with_caps and srt_path and srt_path.exists():
            cmd += ["-vf", f"subtitles='{srt_path}'"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)]
        return _run(cmd)

    captioned = bool(srt_path and srt_path.exists())
    ok = concat(captioned)
    if ok.returncode != 0 and captioned:  # libass may be unavailable — fall back
        log.warning("captioned concat failed; retrying without captions")
        captioned = False
        ok = concat(False)
    if ok.returncode != 0:
        raise RuntimeError(f"concat failed: {ok.stderr[-400:]}")

    out_dur = probe_duration(out)
    return {
        "source_duration_ms": int(analysis.duration * 1000),
        "output_duration_ms": int(out_dur * 1000),
        "segments": len(analysis.segments),
        "sped_up": sped,
        "zoomed": zoomed,
        "captions": captioned,
    }
