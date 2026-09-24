"""Documentation snapshots: which moment of the recording to show for a step, and
how to draw the click highlight on it.

Why a click offset: click `t_ms` comes from the recorder's own clock while the
first encoded frame lands 100-300 ms later (MediaRecorder start-up), and a frame
taken slightly *after* the click shows the pressed/hover state — both argue for
grabbing ~150 ms late rather than exactly at the click.

Why annotation depends on the capture source: extension/auto sessions record the
bbox in the captured tab's coordinate space, so normalising by the viewport maps
onto the frame at any device pixel ratio. The web recorder records clicks on the
RevEase page itself (not the captured screen), so its boxes would land in the
wrong place — those sessions get clean frames.

Everything but `grab_frame`/`make_snapshot` is pure so it is exhaustively
testable without ffmpeg.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from app.docwriter import bbox_to_norm
from app.models import MediaAsset
from app.storage import store

log = logging.getLogger("refract.pipeline.docshots")

BRAND_TEAL = (30, 143, 142)  # --brand #1e8f8e
MIN_BOX_PX = 24
ANNOTATED_SOURCES = ("extension", "auto")


def annotate_policy(source_type: str | None) -> bool:
    return (source_type or "") in ANNOTATED_SOURCES


def pick_snapshot_time(
    step: dict[str, Any],
    clicks: list[tuple[int, float, float]],
    duration_s: float,
    *,
    click_offset_s: float = 0.15,
) -> tuple[float, str]:
    """(seconds, reason). click steps use the recorded click inside the step
    window (+offset); inputs show the typed value near the end; navigations wait
    for the page to settle; anything else takes the step start plus a little."""
    t0 = float(step.get("t_start") or 0.0)
    t1_raw = step.get("t_end")
    t1 = float(t1_raw) if t1_raw is not None else t0
    if t1 < t0:
        t1 = t0
    span = t1 - t0
    action = step.get("action")

    if action == "click":
        lo = t0 - 0.25
        hits = sorted(c[0] / 1000.0 for c in clicks if lo <= c[0] / 1000.0 <= t1)
        if hits:
            t, reason = hits[0] + click_offset_s, "click"
        else:
            t, reason = t0 + min(0.5, span / 2), "start_offset"
    elif action == "input":
        t, reason = max(t0, t1 - 0.2), "input_end"
    elif action == "navigation":
        t, reason = (min(t1, t0 + 1.0) if span > 0 else t0 + 1.0), "nav_settled"
    else:
        t, reason = t0 + min(0.5, span / 2), "start_offset"

    t = max(0.0, t)
    if duration_s and duration_s > 0:
        t = min(t, max(0.0, duration_s - 0.05))
    return round(t, 3), reason


def bbox_to_frame_norm(bbox: Any, viewport: dict[str, Any] | None) -> list[float] | None:
    """[x,y,w,h] viewport px -> 0..1 of the frame. Zero-size (point) boxes are
    kept; the annotator draws a ring for them."""
    return bbox_to_norm(bbox, viewport)


def annotate(
    img,
    bbox_norm: list[float] | None,
    *,
    color: tuple[int, int, int] = BRAND_TEAL,
    pad_px: int = 8,
    border_px: int = 4,
    fill_alpha: int = 46,
    radius_px: int = 10,
    ring_radius_px: int = 28,
):
    """Rounded highlight rectangle (semi-transparent fill + solid border) over the
    bbox, or a ring for a point click. Returns a new RGB image; the input is
    never modified."""
    from PIL import Image, ImageDraw

    base = img.convert("RGBA")
    if not bbox_norm:
        return base.convert("RGB")
    W, H = base.size
    x, y, w, h = (float(v) for v in bbox_norm)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fill = (*color, fill_alpha)
    outline = (*color, 255)

    if w * W < 2 and h * H < 2:
        cx, cy, r = x * W, y * H, ring_radius_px
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=border_px)
    else:
        x0, y0 = x * W - pad_px, y * H - pad_px
        x1, y1 = (x + w) * W + pad_px, (y + h) * H + pad_px
        if x1 - x0 < MIN_BOX_PX:
            cx = (x0 + x1) / 2
            x0, x1 = cx - MIN_BOX_PX / 2, cx + MIN_BOX_PX / 2
        if y1 - y0 < MIN_BOX_PX:
            cy = (y0 + y1) / 2
            y0, y1 = cy - MIN_BOX_PX / 2, cy + MIN_BOX_PX / 2
        x0, y0 = max(border_px / 2, x0), max(border_px / 2, y0)
        x1, y1 = min(W - border_px / 2, x1), min(H - border_px / 2, y1)
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius_px, fill=fill, outline=outline, width=border_px)

    return Image.alpha_composite(base, overlay).convert("RGB")


def grab_frame(video: Path, t: float):
    """One frame at `t` seconds as a PIL image, or None (ffmpeg `-ss` before `-i`
    is frame-accurate on modern builds)."""
    from worker.pipeline.autoedit import _grab

    return _grab(video, t)


def encode_jpeg(img, *, max_w: int = 1600, quality: int = 88) -> bytes:
    from PIL import Image

    im = img.convert("RGB")
    if im.size[0] > max_w:
        ratio = max_w / im.size[0]
        im = im.resize((max_w, max(1, round(im.size[1] * ratio))), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def snapshot_keys(session_id: str, step_id: str, t: float) -> tuple[str, str]:
    """(annotated_or_display_key, raw_key) under the session so project deletion
    purges them with everything else."""
    base = f"sessions/{session_id}/docshots/{step_id}_{int(round(t * 1000))}"
    return f"{base}.jpg", f"{base}_raw.jpg"


def nearest_keyframe(t: float, keyframes: list[tuple[float, str]]) -> str | None:
    if not keyframes:
        return None
    return min(keyframes, key=lambda kf: abs(float(kf[0]) - t))[1]


def _open_stored(key: str | None):
    if not key:
        return None
    try:
        from PIL import Image

        p = store.fetch(key)
        if p is not None:
            return Image.open(p)
    except Exception as e:  # pragma: no cover - corrupt media
        log.warning("docshots: cannot open %s (%s)", key, e)
    return None


def make_snapshot(
    db,
    session_id: str,
    video: Path | None,
    step_id: str,
    t: float,
    bbox_norm: list[float] | None,
    *,
    keyframes: list[tuple[float, str]] | None = None,
    graph_screenshot: str | None = None,
    doc_version: int = 0,
    max_w: int = 1600,
) -> dict[str, Any] | None:
    """Grab (video) -> else nearest 1 fps keyframe -> else the graph's screenshot
    -> else None. Writes the raw frame and, when a bbox is given, the annotated
    one; records a `docshot` MediaAsset. Returns the DocSnapshot dict."""
    img, source = (grab_frame(video, t) if video else None), "video"
    if img is None:
        img, source = _open_stored(nearest_keyframe(t, keyframes or [])), "keyframe"
    if img is None:
        img, source = _open_stored(graph_screenshot), "screenshot"
    if img is None:
        return None

    img = img.convert("RGB")
    key, raw_key = snapshot_keys(session_id, step_id, t)
    raw_bytes = encode_jpeg(img, max_w=max_w)
    store.write(raw_key, raw_bytes)
    annotated = bbox_norm is not None
    store.write(key, encode_jpeg(annotate(img, bbox_norm), max_w=max_w) if annotated else raw_bytes)
    db.add(
        MediaAsset(
            session_id=session_id,
            kind="docshot",
            storage_key=key,
            meta_json={
                "t": t,
                "step_id": step_id,
                "doc_version": doc_version,
                "annotated": annotated,
                "source": source,
                "raw_key": raw_key,
            },
        )
    )
    return {"key": key, "raw_key": raw_key, "t": t, "bbox_norm": bbox_norm, "pending": False}
