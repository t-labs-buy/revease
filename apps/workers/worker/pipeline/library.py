"""Media library jobs: normalize an upload, import a recording, remove a
background.

"Any format" in, three formats out, so the renderer and the browser preview
never meet a surprise:

* stills -> `normalized.png` (EXIF orientation applied, alpha kept, longest side
  capped). HEIC/AVIF decode through pillow-heif when present, else ffmpeg.
  An *animated* GIF/WebP is really a clip, so it becomes a video asset.
* clips  -> the original when it is already H.264 in MP4/MOV (the browser and
  ffmpeg both play it), else `normalized.mp4` (H.264, 30 fps CFR, AAC, faststart;
  capped at 1080p — an overlay or inserted clip never needs more). Bounded
  like the media stage: thread cap, timeout, `.part` temp renamed on success.
* audio  -> the original for formats every browser plays (mp3/m4a/aac/wav),
  else `normalized.m4a`.

Every failure lands on the row as `status="error"` + a message the Media tab
shows; nothing here raises into Celery for a bad file (a retry cannot fix it).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from app.config import get_settings
from app.db import SessionLocal
from app.models import LibraryAsset
from app.storage import store
from worker.pipeline import bgremove
from worker.pipeline.media import run_with_progress

log = logging.getLogger("refract.worker.library")

PLAYABLE_AUDIO = {"mp3", "m4a", "aac", "wav"}
MAX_VIDEO_H = 1080

try:  # optional: HEIC / AVIF stills from phones
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001 - ffmpeg fallback below
    pass


def probe(path: Path) -> dict:
    """ffprobe summary: {duration_ms, width, height, vcodec, has_audio, has_video, frames}."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,codec_name,width,height,nb_frames",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    info = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    try:
        dur = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return {
        "duration_ms": int(dur * 1000) if dur > 0 else None,
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "vcodec": (video or {}).get("codec_name"),
        "format": (info.get("format") or {}).get("format_name") or "",
        "has_video": video is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def _commit_file(key: str, src: Path) -> None:
    dst = store.local_path(key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    store.commit(key)


def _poster(video: Path, a: LibraryAsset, duration_ms: int | None) -> None:
    key = f"library/{a.id}/poster.jpg"
    out = store.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = min(1.0, (duration_ms or 0) / 2000)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
         "-vf", "scale='min(640,iw)':-2", "-q:v", "4", str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and out.exists():
        store.commit(key)
        a.poster_key = key


# --------------------------------------------------------------------------- #
# per-kind normalization
# --------------------------------------------------------------------------- #
def _is_animated(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            return bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
    except Exception:  # noqa: BLE001
        return False


def _open_still(path: Path, work: Path) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
        return im
    except Exception:  # noqa: BLE001 - HEIC without pillow-heif, odd TIFFs, …
        tmp = work / "decoded.png"
        proc = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-frames:v", "1", str(tmp)],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not tmp.exists():
            raise ValueError("this image format could not be read") from None
        im = Image.open(tmp)
        im.load()
        return im


def normalize_image(a: LibraryAsset, src: Path, work: Path) -> None:
    im = ImageOps.exif_transpose(_open_still(src, work))
    has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    im = im.convert("RGBA" if has_alpha else "RGB")
    cap = get_settings().library_max_image_px
    if max(im.size) > cap:
        im.thumbnail((cap, cap), Image.Resampling.LANCZOS)
    key = f"library/{a.id}/normalized.png"
    out = store.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG", optimize=True)
    store.commit(key)
    a.normalized_key = key
    a.poster_key = key
    a.width, a.height = im.size
    a.duration_ms = None
    a.has_audio = 0


def normalize_video(a: LibraryAsset, src: Path, work: Path) -> None:
    info = probe(src)
    if not info["has_video"]:
        raise ValueError("no video track in this file")
    reuse = (info["vcodec"] == "h264" and ("mp4" in info["format"] or "mov" in info["format"])
             and (info["height"] or 0) <= MAX_VIDEO_H and info["duration_ms"])
    if reuse:
        a.normalized_key = a.storage_key
        out = src
    else:
        s = get_settings()
        key = f"library/{a.id}/normalized.mp4"
        out = store.local_path(key)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name("normalized.part.mp4")
        cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", str(src),
               "-vf", f"scale=-2:'min({MAX_VIDEO_H},ih)',fps={s.media_normalize_fps},format=yuv420p",
               "-c:v", "libx264", "-preset", s.media_normalize_preset, "-crf", "20",
               "-threads", str(s.media_threads)]
        cmd += ["-c:a", "aac", "-b:a", "160k", "-ar", "44100"] if info["has_audio"] else ["-an"]
        cmd += ["-movflags", "+faststart", str(tmp)]
        try:
            run_with_progress(cmd, (info["duration_ms"] or 0) / 1000, None,
                              timeout_s=s.media_normalize_timeout_s)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        store.commit(key)
        a.normalized_key = key
        info = {**probe(out), "has_audio": info["has_audio"]}
    a.kind = "video"
    a.width, a.height = info["width"], info["height"]
    a.duration_ms = info["duration_ms"]
    a.has_audio = int(bool(info["has_audio"]))
    _poster(out, a, a.duration_ms)


def normalize_audio(a: LibraryAsset, src: Path, work: Path) -> None:
    info = probe(src)
    if not info["has_audio"]:
        raise ValueError("no audio track in this file")
    if a.ext in PLAYABLE_AUDIO:
        a.normalized_key = a.storage_key
    else:
        key = f"library/{a.id}/normalized.m4a"
        out = store.local_path(key)
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "192k",
                               str(out)], capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise ValueError("this audio format could not be converted")
        store.commit(key)
        a.normalized_key = key
    a.duration_ms = info["duration_ms"]
    a.has_audio = 1


def _work_dir(asset_id: str) -> Path:
    d = get_settings().data_dir / "tmp" / f"library_{asset_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process_asset(asset_id: str) -> dict:
    """Normalize one uploaded library file; status ends `ready` or `error`."""
    db = SessionLocal()
    work = _work_dir(asset_id)
    try:
        a = db.get(LibraryAsset, asset_id)
        if a is None:
            return {"skipped": "asset deleted"}
        try:
            src = store.fetch(a.storage_key)
            if src is None:
                raise ValueError("the uploaded file is missing")
            a.size = a.size or src.stat().st_size
            if a.kind == "image" and _is_animated(src):
                a.kind = "video"  # an animated GIF/WebP is a clip, not a still
            if a.kind == "image":
                normalize_image(a, src, work)
            elif a.kind == "video":
                normalize_video(a, src, work)
            else:
                normalize_audio(a, src, work)
            a.status = "ready"
            a.error = None
        except Exception as e:  # noqa: BLE001 - a bad file is a user-facing error, not a retry
            log.warning("library asset %s failed: %s", asset_id, e)
            a.status = "error"
            a.error = str(e)[:500] or "processing failed"
        db.commit()
        return {"status": a.status, "kind": a.kind}
    finally:
        db.close()
        shutil.rmtree(work, ignore_errors=True)


def import_recording(asset_id: str) -> dict:
    """Copy another project's processed recording into the library, so deleting
    that project later never breaks a video that reuses it."""
    db = SessionLocal()
    try:
        a = db.get(LibraryAsset, asset_id)
        if a is None:
            return {"skipped": "asset deleted"}
        src = store.fetch(a.storage_key)
        if src is None:
            a.status, a.error = "error", "the recording's video is no longer available"
            db.commit()
            return {"status": a.status}
        key = f"library/{a.id}/original.{a.ext or 'mp4'}"
        _commit_file(key, src)
        a.storage_key = key
        a.size = src.stat().st_size
        db.commit()
    finally:
        db.close()
    return process_asset(asset_id)


def remove_background(asset_id: str) -> dict:
    """Write `nobg.png` (the original stays) and flip `bg_status` to ready."""
    db = SessionLocal()
    try:
        a = db.get(LibraryAsset, asset_id)
        if a is None:
            return {"skipped": "asset deleted"}
        try:
            src = store.fetch(a.normalized_key or a.storage_key)
            if src is None:
                raise ValueError("the image is missing")
            with Image.open(src) as im:
                im.load()
                cut, method = bgremove.cutout(im)
            key = f"library/{a.id}/nobg.png"
            out = store.local_path(key)
            out.parent.mkdir(parents=True, exist_ok=True)
            cut.save(out, "PNG", optimize=True)
            store.commit(key)
            a.nobg_key = key
            a.bg_status = "ready"
            a.error = None
        except Exception as e:  # noqa: BLE001
            log.warning("background removal for %s failed: %s", asset_id, e)
            a.bg_status = "error"
            a.error = str(e)[:500] or "background removal failed"
            method = None
        db.commit()
        return {"bg_status": a.bg_status, "method": method}
    finally:
        db.close()
