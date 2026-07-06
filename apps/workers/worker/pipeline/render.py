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
from worker.pipeline.tts import synth_step

log = logging.getLogger("refract.pipeline.render")

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
FPS = 30
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


def _make_still(seg: dict, src_video: Path | None, dims: tuple[int, int], out: Path) -> None:
    """Best still for a segment: its screenshot, else a frame from the raw video at
    the step's start, else a slate. Normalized to cover WxH."""
    w, h = dims
    cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
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


def _crop_filter(crop: dict | None, dims: tuple[int, int]) -> str | None:
    """Reframe the WxH still to a normalized (0..1) region, then scale back to fill."""
    if not crop or not crop.get("enabled"):
        return None
    cw, ch = float(crop.get("w", 1.0)), float(crop.get("h", 1.0))
    cx, cy = float(crop.get("x", 0.0)), float(crop.get("y", 0.0))
    if cw >= 0.999 and ch >= 0.999 and cx <= 0.001 and cy <= 0.001:
        return None
    w, h = dims
    return f"crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},scale={w}:{h}"


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


def _zoom_filter(zoom: dict | None, dims: tuple[int, int]) -> str:
    """Constant click-centered zoom via scale+crop (robust; ease-in is a V2 nicety)."""
    w, h = dims
    if not zoom or not zoom.get("enabled"):
        return f"scale={w}:{h}"
    scale = max(1.0, float(zoom.get("scale", 1.6)))
    sw, sh = int(w * scale), int(h * scale)
    cx, cy = float(zoom.get("cx", 0.5)), float(zoom.get("cy", 0.5))
    # crop offset toward the click, clamped inside the scaled frame
    x = f"min(max({cx}*{sw}-{w}/2\\,0)\\,{sw}-{w})"
    y = f"min(max({cy}*{sh}-{h}/2\\,0)\\,{sh}-{h})"
    return f"scale={sw}:{sh},crop={w}:{h}:{x}:{y}"


def _render_segment(seg, seg_tl, src_video, dims, captions, font, work: Path,
                    crop=None, elements=None, logo: Path | None = None,
                    logo_pos: str = "Top Right") -> tuple[Path, bool]:
    """Return (clip_path, rendered_now). Reuses a cached clip when the content hash
    matches — this is what makes regenerate touch only changed segments."""
    script = effective_script(seg.get("words", []), seg.get("removed", []))
    tts_path = Path(seg["_audio_path"])  # precomputed in run_render (TTS or original audio)
    dur_s = max(0.3, seg_tl.out_duration_ms / 1000.0)

    clip_hash = _sha(seg.get("step_id"), script, tts_path.name, seg.get("zoom"),
                     dims, captions, seg.get("screenshot"), seg.get("source_start_ms"),
                     crop, elements, str(logo), logo_pos)
    clip = work / f"seg_{seg_tl.index:03d}_{clip_hash}.mp4"
    if clip.exists():
        return clip, False  # reused — unchanged since last render

    still = work / f"still_{clip_hash}.png"
    _make_still(seg, src_video, dims, still)

    # crop (reframe) -> zoom -> captions -> overlay elements -> normalize
    parts: list[str] = []
    cf = _crop_filter(crop, dims)
    if cf:
        parts.append(cf)
    parts.append(_zoom_filter(seg.get("zoom"), dims))
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

    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur_s:.3f}", "-i", str(still), "-i", str(tts_path)]
    if logo is not None:
        cmd += ["-i", str(logo)]  # index 2
        lh = int(dims[1] / 9)
        fc = f"[0:v]{vf}[base];[2:v]scale=-1:{lh}[lg];[base][lg]overlay={_overlay_xy(logo_pos)}[v]"
    else:
        fc = f"[0:v]{vf}[v]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "1:a",
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


def _extract_audio(src_video: Path, start_ms: int, end_ms: int, out: Path) -> int:
    """Extract the original narration for a step's source window. Returns duration ms."""
    dur_ms = max(300, end_ms - start_ms)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-y", "-ss", f"{start_ms / 1000:.3f}", "-t", f"{dur_ms / 1000:.3f}",
        "-i", str(src_video), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(out),
    ])
    return dur_ms


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
        src_video = _find_source_video(db, vp.project_id)

        segs = spec.get("segments", [])
        crop = spec.get("crop")
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

        # Motion/mouse auto-zoom: for each scene, find where the on-screen activity
        # (cursor movement / clicks cause localized UI change) is and zoom toward it.
        # Only touches scenes that don't already have an explicit (bbox/user) zoom.
        if spec.get("motion_zoom", True) and src_video is not None:
            from worker.pipeline.autoedit import _motion_centroid, probe_dims

            vdims = probe_dims(src_video)
            zoomed_auto = 0
            for s in segs:
                z = s.get("zoom") or {}
                if z.get("enabled"):
                    continue  # keep an existing bbox / user zoom
                t0 = s.get("source_start_ms", 0) / 1000.0
                t1 = max(s.get("source_end_ms", 0) / 1000.0, t0 + 0.6)
                cx, cy, scale = _motion_centroid(src_video, t0, t1, vdims)
                if scale > 1.0:
                    s["zoom"] = {
                        "enabled": True,
                        "scale": round(min(1.8, scale), 3),
                        "cx": cx,
                        "cy": cy,
                        "speed": 3,
                    }
                    zoomed_auto += 1
            log.info("motion auto-zoom: %d/%d scenes", zoomed_auto, len(segs))

        # per-step audio (TTS, or the original narration if "use original voice") -> timeline
        step_inputs = []
        tts_synth = tts_cached = 0
        for s in segs:
            script = effective_script(s.get("words", []), s.get("removed", []))
            if use_original:
                apath = work / f"orig_{s['step_id']}.wav"
                dur_ms = _extract_audio(
                    src_video, s.get("source_start_ms", 0), s.get("source_end_ms", 0), apath
                )
                s["_audio_path"] = str(apath)
            else:
                r = synth_step(script, media_root=store.root,
                               voice_id=voice["voice_id"], speed=voice.get("speed", 1.0))
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
                                        crop=crop, elements=elements, logo=logo, logo_pos=logo_pos)
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


def _find_source_video(db, project_id: str) -> Path | None:
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
                return p
    return None
