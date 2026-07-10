"""FFmpeg-first render (master §Phase-4 E4/E5) + the regenerate loop (E6).

Each step becomes a self-contained segment clip (a still — screenshot or a frame
pulled from the raw video — with a click-centered zoom, its per-step TTS as audio,
and burned captions). Clips are cached by a content hash, so re-rendering after an
edit re-renders ONLY the changed segments and reuses the rest — that IS the
regenerate loop, and it is provable via the returned stats.

The output clock comes entirely from buildTimeline, so audio never drifts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.editspec import effective_script
from app.models import MediaAsset, RenderJob, VideoProject, WorkflowGraphRow
from app.storage import store
from worker.pipeline.timeline import StepInput, build_timeline
from worker.pipeline.tts import _silent_wav, synth_step

log = logging.getLogger("refract.pipeline.render")

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
FPS = 30
# Product-video pacing: scenes with no narration are idle/boring stretches —
# fast-forward them instead of playing them out in real time, and NEVER let one
# idle stretch (no voice, often no motion) occupy more than SILENT_MAX_MS of the
# output regardless of how long it ran in the source.
SILENT_SPEEDUP = 2.5
SILENT_MAX_MS = 3500
DEFAULT_PACE = 1.1  # global tempo for narrated scenes (voice + footage together)

# Backdrop presets behind the (inset) recording — ids match the web editor.
BG_PRESETS: dict[str, tuple[str, str | None]] = {
    "slate": ("0b0f1a", "1e2637"),
    "indigo": ("6d5dfb", "a855f7"),
    "ocean": ("0ea5e9", "6366f1"),
    "sunset": ("f97316", "ec4899"),
    "forest": ("10b981", "0d9488"),
    "light": ("e2e8f0", "f8fafc"),
}
BG_INSET = 0.88  # recording occupies 88% of the frame when a backdrop is on


def _bg_source(style: str | None, dims: tuple[int, int]) -> str:
    """lavfi source for the backdrop (gradient or flat color)."""
    w, h = dims
    c0, c1 = BG_PRESETS.get(style or "", ("0b0f1a", "1e2637"))
    if not c1:
        return f"color=c=0x{c0}:s={w}x{h}"
    return f"gradients=s={w}x{h}:c0=0x{c0}:c1=0x{c1}:x0=0:y0=0:x1={w}:y1={h}"
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]


def _font() -> str | None:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def _run(cmd: list[str]) -> bool:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log.warning("ffmpeg cmd failed: %s\n%s", " ".join(cmd), proc.stderr[-800:])
        return False
    return True


def _sha(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _drawtext(font: str | None, textfile: Path, size: int, y: str) -> str | None:
    if not font:
        return None
    return (
        f"drawtext=fontfile={font}:textfile={textfile}:fontcolor=white:fontsize={size}"
        f":box=1:boxcolor=black@0.55:boxborderw=14:x=(w-text_w)/2:y={y}"
    )


def _make_still(seg: dict, src_video: Path | None, dims: tuple[int, int], out: Path,
                crop: dict | None = None) -> None:
    """Best still for a segment: its screenshot, else a frame from the raw video at
    the step's start, else a slate. The user crop (normalized to the ORIGINAL
    frame) is applied first, then the result covers WxH."""
    w, h = dims
    pre = _crop_filter(crop)
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    cover = f"{pre},{cover}" if pre else cover
    out.parent.mkdir(parents=True, exist_ok=True)

    shot = seg.get("screenshot")
    if shot:
        p = store.local_path(shot)
        if p.exists() and _run(["ffmpeg", "-y", "-i", str(p), "-vf", cover, "-frames:v", "1", str(out)]):
            return
    if src_video and src_video.exists():
        ss = max(0, seg.get("source_start_ms", 0)) / 1000.0
        if _run(["ffmpeg", "-y", "-ss", f"{ss:.3f}", "-i", str(src_video), "-vf", cover,
                 "-frames:v", "1", str(out)]):
            return
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0b0f1a:s={w}x{h}", "-frames:v", "1", str(out)])


def _crop_for_segment(crops: list[dict] | None, seg: dict) -> dict | None:
    """The crop that applies to THIS scene. Each crop can carry its own time
    window (start_ms/end_ms) so different parts of the recording get different
    reframes — the first enabled crop whose window overlaps the scene wins; a
    crop without a window applies everywhere. Scenes matching none render
    uncropped."""
    for crop in crops or []:
        if not crop or not crop.get("enabled"):
            continue
        s_ms, e_ms = int(crop.get("start_ms") or 0), int(crop.get("end_ms") or 0)
        if e_ms > s_ms:
            if seg.get("source_end_ms", 0) <= s_ms or seg.get("source_start_ms", 0) >= e_ms:
                continue
        return crop
    return None


def _remap_zoom_into_crop(zoom: dict | None, crop: dict | None) -> dict | None:
    """Zoom centers (click positions) are normalized to the ORIGINAL frame; when a
    crop reframes the scene first, remap the center into cropped coordinates so
    the zoom still aims at the same on-screen spot."""
    if not zoom or not zoom.get("enabled") or not crop:
        return zoom
    cw = min(1.0, max(0.05, float(crop.get("w", 1.0))))
    ch = min(1.0, max(0.05, float(crop.get("h", 1.0))))
    cx = min(max(0.0, float(crop.get("x", 0.0))), 1.0 - cw)
    cy = min(max(0.0, float(crop.get("y", 0.0))), 1.0 - ch)
    return {
        **zoom,
        "cx": min(1.0, max(0.0, (float(zoom.get("cx", 0.5)) - cx) / cw)),
        "cy": min(1.0, max(0.0, (float(zoom.get("cy", 0.5)) - cy) / ch)),
    }


def _crop_filter(crop: dict | None) -> str | None:
    """Cut the normalized (0..1) region out of the ORIGINAL frame — the same frame
    the crop was drawn on in the editor. It runs BEFORE any cover/scale so the
    coordinates always line up; the caller then covers the output WxH, so only
    the selected content ends up in the video (no source padding leaks back in).
    The region is clamped inside the frame (x+w ≤ 1) so a crop dragged slightly
    past the edge still shows exactly the selected area."""
    if not crop or not crop.get("enabled"):
        return None
    cw = min(1.0, max(0.05, float(crop.get("w", 1.0))))
    ch = min(1.0, max(0.05, float(crop.get("h", 1.0))))
    cx = min(max(0.0, float(crop.get("x", 0.0))), 1.0 - cw)
    cy = min(max(0.0, float(crop.get("y", 0.0))), 1.0 - ch)
    if cw >= 0.999 and ch >= 0.999 and cx <= 0.001 and cy <= 0.001:
        return None
    return f"crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f}"


def _hex(color: str, default: str) -> str:
    c = (color or default).lstrip("#")
    return c if all(ch in "0123456789abcdefABCDEF" for ch in c) and len(c) in (6, 8) else default.lstrip("#")


def _el_active(el: dict, seg_start_ms: int, seg_end_ms: int) -> bool:
    """An element with a time window shows only on scenes it overlaps; without one
    (end<=start) it shows across the whole video."""
    s, e = int(el.get("start_ms", 0) or 0), int(el.get("end_ms", 0) or 0)
    if e <= s:
        return True
    return s <= seg_end_ms and e >= seg_start_ms


def _element_filters(elements, dims: tuple[int, int], font: str | None, work: Path, tag: str,
                     seg_start_ms: int = 0, seg_end_ms: int = 0) -> list[str]:
    """Overlay text / highlight boxes on top of the frame (screen-space, normalized)."""
    w, h = dims
    out: list[str] = []
    for i, el in enumerate(elements or []):
        if not _el_active(el, seg_start_ms, seg_end_ms):
            continue
        et = el.get("type")
        x, y = int(float(el.get("x", 0.1)) * w), int(float(el.get("y", 0.1)) * h)
        ew, eh = int(float(el.get("w", 0.2)) * w), int(float(el.get("h", 0.1)) * h)
        if et == "box":
            c = _hex(el.get("color"), "facc15")
            out.append(f"drawbox=x={x}:y={y}:w={ew}:h={eh}:color=0x{c}@0.30:t=fill")
            out.append(f"drawbox=x={x}:y={y}:w={ew}:h={eh}:color=0x{c}@0.95:t=3")
        elif et == "text" and font:
            text = str(el.get("text") or "").strip()
            if not text:
                continue
            tf = work / f"el_{tag}_{i}.txt"
            tf.write_text(text)
            c = _hex(el.get("color"), "ffffff")
            size = max(12, int(float(el.get("size", 0.06)) * h))
            out.append(
                f"drawtext=fontfile={font}:textfile={tf}:fontcolor=0x{c}:fontsize={size}"
                f":x={x}:y={y}:box=1:boxcolor=black@0.40:boxborderw=8"
            )
    return out


def _zoom_filter(zoom: dict | None, dims: tuple[int, int], dur_s: float = 3.0) -> str:
    """Animated click-centered zoom: the viewport eases in toward (cx, cy) like a
    camera move, then holds — the production 'pan + zoom' feel. `speed` (1 slow …
    5 snappy) sets how fast the ease-in lands."""
    w, h = dims
    if not zoom or not zoom.get("enabled"):
        return f"scale={w}:{h}"
    scale = max(1.0, float(zoom.get("scale", 1.6)))
    cx = min(1.0, max(0.0, float(zoom.get("cx", 0.5))))
    cy = min(1.0, max(0.0, float(zoom.get("cy", 0.5))))
    ease_s = {1: 2.0, 2: 1.5, 3: 1.1, 4: 0.7, 5: 0.4}.get(int(zoom.get("speed", 3) or 3), 1.1)
    ease_frames = max(1, int(FPS * min(ease_s, max(0.3, dur_s))))
    step = max(0.0005, round((scale - 1.0) / ease_frames, 5))
    z = f"min(zoom+{step},{scale})"
    x = f"iw*{cx}-(iw/zoom/2)"
    y = f"ih*{cy}-(ih/zoom/2)"
    return f"scale={w}:{h},zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={FPS}"


def _render_segment(seg, seg_tl, src_video, dims, captions, font, work: Path,
                    crops=None, elements=None, logo: Path | None = None,
                    logo_pos: str = "Top Right", background: dict | None = None) -> tuple[Path, bool]:
    """Return (clip_path, rendered_now). Reuses a cached clip when the content hash
    matches — this is what makes regenerate touch only changed segments.

    The clip shows the REAL source footage for the scene's window, retimed to fit
    the narration slot (sped up when the window is longer than the narration;
    played at natural pace + last-frame freeze when shorter). A still is only the
    fallback when there is no usable footage."""
    script = effective_script(seg.get("words", []), seg.get("removed", []))
    tts_path = Path(seg["_audio_path"])  # precomputed in run_render (TTS or original audio)
    dur_s = max(0.3, seg_tl.out_duration_ms / 1000.0)
    src_len_s = max(0.0, (seg_tl.source_end_ms - seg_tl.source_start_ms) / 1000.0)
    use_footage = (
        src_video is not None and src_video.exists() and not seg_tl.hold and src_len_s >= 0.2
    )

    # each crop honours its optional time window, and the zoom center is remapped
    # into the cropped frame so it still points at the same on-screen spot
    crop_eff = _crop_for_segment(crops, seg)
    zoom_eff = _remap_zoom_into_crop(seg.get("zoom"), crop_eff)

    clip_hash = _sha("v4", seg.get("step_id"), script, tts_path.name, zoom_eff,
                     dims, captions, seg.get("screenshot"), seg.get("source_start_ms"),
                     seg.get("source_end_ms"), round(dur_s, 3), use_footage,
                     crop_eff, elements, str(logo), logo_pos, background)
    clip = work / f"seg_{seg_tl.index:03d}_{clip_hash}.mp4"
    if clip.exists():
        return clip, False  # reused — unchanged since last render

    w, h = dims
    parts: list[str] = []
    cf = _crop_filter(crop_eff)
    if use_footage:
        # crop the ORIGINAL frame first (the frame the crop was drawn on), then
        # normalize the remaining content to cover WxH — only the selected
        # region reaches the output, so source padding can't leak back in
        if cf:
            parts.append(cf)
        parts.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        speed = src_len_s / dur_s
        if speed >= 1.02:
            parts.append(f"setpts=PTS/{speed:.6f}")  # play faster to fit the slot
        elif dur_s > src_len_s + 0.05:
            # narration outlasts the window: natural pace, then hold the last frame
            parts.append(f"tpad=stop_mode=clone:stop_duration={dur_s - src_len_s:.3f}")
    else:
        still = work / f"still_{clip_hash}.png"
        _make_still(seg, src_video, dims, still, crop=crop_eff)  # crop baked into the still

    # zoom -> captions -> overlay elements -> normalize
    parts.append(_zoom_filter(zoom_eff, dims, dur_s))
    if captions and script:
        capfile = work / f"cap_{clip_hash}.txt"
        capfile.write_text(script)
        dt = _drawtext(font, capfile, size=int(dims[0] / 36), y="h-th-40")
        if dt:
            parts.append(dt)
    parts.extend(_element_filters(elements, dims, font, work, clip_hash,
                                  seg.get("source_start_ms", 0), seg.get("source_end_ms", 0)))
    parts += ["format=yuv420p", f"fps={FPS}", "setsar=1"]
    vf = ",".join(parts)

    if use_footage:
        ss = seg_tl.source_start_ms / 1000.0
        cmd = ["ffmpeg", "-y", "-ss", f"{ss:.3f}", "-t", f"{src_len_s:.3f}",
               "-i", str(src_video), "-i", str(tts_path)]
    else:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(still), "-i", str(tts_path)]

    # Compose: main video -> (inset on backdrop) -> (logo watermark).
    bg_on = bool(background and background.get("enabled"))
    idx = 2  # next ffmpeg input index (0 = video/still, 1 = narration audio)
    logo_idx = bg_idx = None
    if logo is not None:
        logo_idx = idx
        idx += 1
        cmd += ["-i", str(logo)]
    if bg_on:
        bg_idx = idx
        idx += 1
        cmd += ["-f", "lavfi", "-i", _bg_source(background.get("style"), dims)]

    steps = [f"[0:v]{vf}[main]"]
    last = "main"
    if bg_on:
        steps.append(f"[{last}]scale=iw*{BG_INSET}:ih*{BG_INSET}[inset]")
        steps.append(f"[{bg_idx}:v][inset]overlay=(W-w)/2:(H-h)/2[backed]")
        last = "backed"
    if logo_idx is not None:
        lh = int(dims[1] / 9)
        steps.append(f"[{logo_idx}:v]scale=-1:{lh}[lg]")
        steps.append(f"[{last}][lg]overlay={_overlay_xy(logo_pos)}[branded]")
        last = "branded"
    fc = ";".join(steps)
    cmd += ["-filter_complex", fc, "-map", f"[{last}]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "24000", "-shortest", "-t", f"{dur_s:.3f}", str(clip)]
    ok = _run(cmd)
    if not ok:
        raise RuntimeError(f"segment {seg_tl.index} render failed")
    return clip, True


def _fetch_logo(url: str, dest: Path) -> Path | None:
    """Download a brand logo (best-effort) to a local file for ffmpeg overlay."""
    if not url:
        return None
    try:
        import urllib.request

        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "refract"})
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            dest.write_bytes(r.read())
        # verify ffmpeg can read it as an image
        if _run(["ffprobe", "-v", "error", "-i", str(dest)]):
            return dest
    except Exception as e:  # pragma: no cover - network dependent
        log.warning("logo fetch failed (%s)", e)
    return None


def _overlay_xy(position: str, margin: int = 28) -> str:
    p = (position or "Top Right").lower()
    x = f"W-w-{margin}" if "right" in p else f"{margin}"
    y = f"H-h-{margin}" if "bottom" in p else f"{margin}"
    if "center" in p:
        x = "(W-w)/2"
    return f"{x}:{y}"


def _render_titlecard(text, dur_ms, dims, font, work, tag, brand: dict | None = None, logo: Path | None = None) -> Path:
    w, h = dims
    dur_s = max(0.5, dur_ms / 1000.0)
    chash = _sha(tag, text, dur_ms, dims, brand, str(logo))
    clip = work / f"{tag}_{chash}.mp4"
    if clip.exists():
        return clip
    capfile = work / f"{tag}_{chash}.txt"
    capfile.write_text(text or "")
    dt = _drawtext(font, capfile, size=int(w / 20), y="(h-th)/2")

    # background: brand gradient (primary -> accent) or the default dark slate
    inputs = ["-f", "lavfi"]
    if brand:
        c0 = _hex(brand.get("primary_color"), "6d5dfb")
        c1 = _hex(brand.get("accent_color"), "a855f7")
        inputs += ["-i", f"gradients=s={w}x{h}:c0=0x{c0}:c1=0x{c1}:x0=0:y0=0:x1={w}:y1={h}"]
    else:
        inputs += ["-i", f"color=c=0x0b0f1a:s={w}x{h}"]
    inputs += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono"]

    steps = [f"[0:v]scale={w}:{h}[bg]"]
    last = "bg"
    if logo is not None:
        inputs += ["-i", str(logo)]  # index 2
        lh = int(h / 5)
        steps.append(f"[2:v]scale=-1:{lh}[lg]")
        steps.append(f"[{last}][lg]overlay=(W-w)/2:{int(h*0.20)}[bl]")
        last = "bl"
    tail = (dt + ",") if dt else ""
    steps.append(f"[{last}]{tail}format=yuv420p,fps={FPS},setsar=1[v]")
    fc = ";".join(steps)

    _run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc, "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "24000", "-t", f"{dur_s:.3f}", str(clip),
    ])
    return clip


def _extract_audio(src_video: Path, start_ms: int, end_ms: int, out: Path, tempo: float = 1.0) -> int:
    """Extract the original narration for a step's source window, optionally
    time-compressed (atempo) for pacing. Returns the OUTPUT duration ms."""
    dur_ms = max(300, end_ms - start_ms)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-t", f"{dur_ms / 1000:.3f}",
           "-i", str(src_video), "-vn", "-ac", "1", "-ar", "24000"]
    if tempo > 1.001:
        cmd += ["-af", f"atempo={min(2.0, tempo):.3f}"]
        dur_ms = int(dur_ms / min(2.0, tempo))
    cmd += ["-c:a", "pcm_s16le", str(out)]
    _run(cmd)
    return max(300, dur_ms)


def run_render(render_job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.get(RenderJob, render_job_id)
        if job is None:
            log.warning("render job %s not found; skipping", render_job_id)
            return {"render_job_id": render_job_id, "skipped": "render job not found"}
        job.status = "running"
        db.commit()

        vp = db.get(VideoProject, job.video_project_id)
        spec = vp.edit_spec_json
        dims = ASPECTS.get(spec.get("aspect", "16:9"), ASPECTS["16:9"])
        captions = bool(spec.get("captions", {}).get("enabled", True))
        voice = spec.get("voice", {"voice_id": "alloy", "speed": 1.0})
        font = _font()

        # source video (if any) for still extraction — from the latest session's asset
        graph = db.scalar(
            select(WorkflowGraphRow)
            .where(WorkflowGraphRow.project_id == vp.project_id)
            .order_by(WorkflowGraphRow.version.desc())
        )
        src_video, src_session_id = _find_source_video(db, vp.project_id)

        segs = spec.get("segments", [])
        # skip: scenes flagged "skipped" are dropped from the render entirely.
        segs = [s for s in segs if not s.get("skipped")]
        # multi-range crops; a spec saved before `crops` existed falls back to the
        # legacy single crop. An explicit empty list means "no crops" (do NOT
        # resurrect the legacy one — the user removed them all).
        crops = spec.get("crops")
        if crops is None:
            crops = [spec["crop"]] if spec.get("crop") else []
        elements = spec.get("elements")
        # trim: keep only scenes whose source start falls inside [start, end].
        trim = spec.get("trim") or {}
        if trim.get("enabled") and trim.get("end_ms", 0) > trim.get("start_ms", 0):
            t0, t1 = trim["start_ms"], trim["end_ms"]
            kept = [s for s in segs if t0 <= s.get("source_start_ms", 0) <= t1]
            if kept:
                segs = kept
        use_original = bool(voice.get("use_original")) and src_video is not None
        work = store.local_path(f"renders/{vp.id}")
        work.mkdir(parents=True, exist_ok=True)

        # Click/motion auto-zoom, for scenes without an explicit (bbox/user) zoom:
        # 1) recorded click telemetry — zoom EXACTLY where the mouse clicked;
        # 2) else frame-diff motion centroid (visual approximation of the click).
        zoomed_click = zoomed_motion = 0
        if spec.get("motion_zoom", True) and src_video is not None:
            from worker.pipeline.autoedit import _motion_centroid, probe_dims

            clicks = _click_points(db, src_session_id)
            vdims = probe_dims(src_video)
            for s in segs:
                z = s.get("zoom") or {}
                if z.get("enabled"):
                    continue  # keep an existing bbox / user zoom
                if z.get("auto") is False:
                    continue  # user explicitly turned zoom OFF for this scene
                t0ms = s.get("source_start_ms", 0)
                t1ms = max(s.get("source_end_ms", 0), t0ms + 600)
                # the click that opens the scene (scene windows start at click time)
                hit = next((c for c in clicks if t0ms - 250 <= c[0] <= t1ms), None)
                if hit:
                    cx, cy, scale = hit[1], hit[2], 1.6
                    zoomed_click += 1
                else:
                    cx, cy, scale = _motion_centroid(src_video, t0ms / 1000.0, t1ms / 1000.0, vdims)
                    zoomed_motion += int(scale > 1.0)
                if scale > 1.0:
                    s["zoom"] = {
                        "enabled": True,
                        "scale": round(min(1.8, scale), 3),
                        "cx": cx,
                        "cy": cy,
                        "speed": 3,
                        "auto": True,  # added by the renderer; user-tweakable in the Zoom tab
                    }
            log.info("auto-zoom: %d click-centered, %d motion-centered of %d scenes",
                     zoomed_click, zoomed_motion, len(segs))
            # Persist the auto-added zooms into the edit spec so they show up in the
            # editor's Zoom tab, where the user can tweak, remove, or add to them.
            if zoomed_click or zoomed_motion:
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(vp, "edit_spec_json")
                db.commit()

        # Product-video pacing: narrated scenes run at `pace` (voice + footage
        # together), silent scenes fast-forward at SILENT_SPEEDUP. This is what
        # turns a 15-min raw capture into a tight demo.
        pace = min(1.5, max(1.0, float(spec.get("pace") or DEFAULT_PACE)))

        # per-step audio (TTS, or the original narration if "use original voice") -> timeline
        step_inputs = []
        tts_synth = tts_cached = 0
        for s in segs:
            script = effective_script(s.get("words", []), s.get("removed", []))
            src_ms = max(0, s.get("source_end_ms", 0) - s.get("source_start_ms", 0))
            if not script.strip():
                # No spoken words in this scene: it's an idle stretch — fast-forward
                # it silently instead of playing it out (or speaking a placeholder),
                # capped so a long dead stretch can't bloat the output.
                dur_ms = max(300, min(SILENT_MAX_MS, int(src_ms / (SILENT_SPEEDUP * pace))))
                apath = work / f"sil_{s['step_id']}_{dur_ms}.wav"
                if not apath.exists():
                    _silent_wav(apath, dur_ms)
                s["_audio_path"] = str(apath)
            elif use_original:
                apath = work / f"orig_{s['step_id']}_{pace:.2f}.wav"
                dur_ms = _extract_audio(
                    src_video, s.get("source_start_ms", 0), s.get("source_end_ms", 0), apath,
                    tempo=pace,
                )
                s["_audio_path"] = str(apath)
            else:
                r = synth_step(script, media_root=store.root,
                               voice_id=voice["voice_id"],
                               speed=voice.get("speed", 1.0) * pace)
                tts_cached += int(r.cached)
                tts_synth += int(not r.cached)
                dur_ms = r.duration_ms
                s["_audio_path"] = str(store.local_path(r.storage_key))
            z = s.get("zoom") or {}
            step_inputs.append(
                StepInput(
                    step_id=s["step_id"],
                    tts_duration_ms=dur_ms,
                    source_start_ms=s.get("source_start_ms", 0),
                    source_end_ms=s.get("source_end_ms", 0),
                    click_x=z.get("cx") if z.get("enabled") else None,
                    click_y=z.get("cy") if z.get("enabled") else None,
                    viewport_w=1, viewport_h=1,  # cx/cy already normalized
                    zoom_enabled=bool(z.get("enabled")),
                    zoom_scale=float(z.get("scale", 1.6)),
                )
            )
        timeline = build_timeline(step_inputs)

        # Brand package: gradient intro/outro cards + a logo watermark on scenes.
        brand = spec.get("brand") or None
        logo = None
        logo_pos = "Top Right"
        if brand:
            logo = _fetch_logo(str(brand.get("logo_url") or ""), work / "brand_logo")
            logo_pos = str(brand.get("logo_position") or "Top Right")

        clips: list[Path] = []
        rendered = reused = 0
        intro = spec.get("intro", {})
        if intro.get("enabled"):
            clips.append(_render_titlecard(intro.get("title", ""), intro.get("duration_ms", 2000),
                                           dims, font, work, "intro", brand=brand, logo=logo))
        for s, seg_tl in zip(segs, timeline.segments):
            clip, did = _render_segment(s, seg_tl, src_video, dims, captions, font, work,
                                        crops=crops, elements=elements, logo=logo, logo_pos=logo_pos,
                                        background=spec.get("background"))
            clips.append(clip)
            rendered += int(did)
            reused += int(not did)
        outro = spec.get("outro", {})
        if outro.get("enabled"):
            clips.append(_render_titlecard(outro.get("title", ""), outro.get("duration_ms", 1500),
                                           dims, font, work, "outro", brand=brand, logo=logo))

        # concat (re-encode for safe, uniform output)
        list_file = work / "concat.txt"
        list_file.write_text("".join(f"file '{c}'\n" for c in clips))
        overall = _sha([c.name for c in clips])
        out_key = f"renders/{vp.id}/final_{overall}.mp4"
        out_path = store.local_path(out_key)
        ok = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                   "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", str(out_path)])
        if not ok:
            raise RuntimeError("concat failed")

        stats = {
            "segments_total": len(segs),
            "segments_rendered": rendered,
            "segments_reused": reused,
            "tts_synth": tts_synth,
            "tts_cached": tts_cached,
            "expected_body_ms": timeline.total_duration_ms,
            "pace": pace,
            "zoom_click": zoomed_click,
            "zoom_motion": zoomed_motion,
            "aspect": spec.get("aspect"),
        }
        job.output_key = out_key
        job.stats_json = stats
        job.status = "done"
        db.commit()
        log.info("render done: %s", stats)
        return {"render_job_id": render_job_id, **stats}
    except Exception as e:
        log.exception("render failed")
        if "job" in dir() and job is not None:
            job.status = "error"
            job.error_json = {"error": str(e)}
            db.commit()
        raise
    finally:
        db.close()


def _find_source_video(db, project_id: str) -> tuple[Path | None, str | None]:
    """Locate the raw source video and the capture session it belongs to (the
    session carries the click telemetry + viewport used for click-centered zoom)."""
    from app.models import CaptureSession

    sess_ids = [
        s.id for s in db.scalars(
            select(CaptureSession).where(CaptureSession.project_id == project_id)
        )
    ]
    for sid in sess_ids:
        asset = db.scalar(
            select(MediaAsset).where(MediaAsset.session_id == sid, MediaAsset.kind == "raw_video")
        )
        if asset:
            p = store.local_path(asset.storage_key)
            if p.exists():
                return p, sid
    return None, None


def _click_points(db, session_id: str | None) -> list[tuple[int, float, float]]:
    """Recorded click positions as [(t_ms, cx, cy)] normalized to the viewport —
    the ground truth for where to center a zoom. Empty when the session has no
    telemetry (plain recorder / upload)."""
    if not session_id:
        return []
    from app.models import CaptureSession, Event

    sess = db.get(CaptureSession, session_id)
    vp = (sess.viewport_json or {}) if sess else {}
    vw, vh = vp.get("w") or 0, vp.get("h") or 0
    if not vw or not vh:
        return []
    out: list[tuple[int, float, float]] = []
    for e in db.scalars(select(Event).where(Event.session_id == session_id, Event.type == "click")):
        b = e.bbox_json
        if isinstance(b, (list, tuple)) and len(b) == 4:
            cx = min(1.0, max(0.0, (float(b[0]) + float(b[2]) / 2) / vw))
            cy = min(1.0, max(0.0, (float(b[1]) + float(b[3]) / 2) / vh))
            out.append((int(e.t_ms), round(cx, 4), round(cy, 4)))
    out.sort()
    return out
