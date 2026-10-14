"""Keyframes as vision-model input. A frame is downscaled before upload: the
model needs to recognise a screen, not read every pixel, and a full-size frame
costs ~10x the tokens. Pillow comes with fpdf2 (the PDF exporter) so the API
needs no new dependency; the worker imports this too."""

from __future__ import annotations

import io
import logging

from app.storage import store

log = logging.getLogger("refract.frames")

FRAME_WIDTH = 768


def frame_jpeg(key: str | None, width: int = FRAME_WIDTH) -> bytes | None:
    """The stored frame `key` as a JPEG at most `width` wide, or None when it is
    missing or unreadable (callers degrade to text-only)."""
    if not key:
        return None
    try:
        from PIL import Image

        path = store.fetch(key)
        if path is None:
            return None
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=70)
            return buf.getvalue()
    except Exception:
        log.warning("could not load frame %s", key)
        return None
