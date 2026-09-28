"""Background removal for library images (logos, product shots) — "remove bg"
in the editor's Media tab.

Preferred: ISNet (general-use), the model rembg ships, run directly through
onnxruntime — already installed for Kokoro TTS — so we avoid rembg's heavy
dependency tree (scikit-image, pymatting, pooch). Preprocessing mirrors rembg's
DisSession exactly (1024² LANCZOS, scale by max, ImageNet mean / unit std,
min-max the predicted mask), because a mismatch there silently degrades the cut.

Fallback (no model file, or onnxruntime missing): key out the colour that fills
the border, but only the region *connected to* the border. A white logo on a
white background loses the background and keeps the white inside the letters,
which a plain colour key would punch through. Deterministic, so the tests run
offline — the same "every provider degrades" rule as TTS and the LLM.

The session is cached per process: loading the 170 MB graph takes ~1 s, and the
light worker handles one image after another.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

log = logging.getLogger("refract.worker.bgremove")

MODEL_FILE = "isnet-general-use.onnx"
SIDE = 1024
MEAN = (0.485, 0.456, 0.406)


def model_path() -> Path:
    from app.config import get_settings

    s = get_settings()
    return Path(s.bg_model_path) if s.bg_model_path else s.data_dir / "models" / MODEL_FILE


@lru_cache(maxsize=1)
def _session(path: str):  # noqa: ANN202 - onnxruntime.InferenceSession
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2  # the light worker runs 3 slots; don't take every core
    return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


def _isnet_mask(img: Image.Image, path: Path) -> Image.Image:
    sess = _session(str(path))
    rgb = img.convert("RGB").resize((SIDE, SIDE), Image.Resampling.LANCZOS)
    x = np.asarray(rgb, dtype=np.float32)
    x = x / max(float(x.max()), 1e-6)
    x = (x - np.array(MEAN, dtype=np.float32)) / 1.0
    x = x.transpose(2, 0, 1)[None, ...].astype(np.float32)
    pred = sess.run(None, {sess.get_inputs()[0].name: x})[0][:, 0, :, :][0]
    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / max(hi - lo, 1e-6)
    mask = Image.fromarray((pred * 255).clip(0, 255).astype(np.uint8), "L")
    return mask.resize(img.size, Image.Resampling.LANCZOS)


def border_key_mask(img: Image.Image, tolerance: float = 40.0, feather: float = 1.2) -> Image.Image:
    """Alpha mask that removes the border-connected region close to the border's
    dominant colour. Pure (Pillow + numpy + OpenCV); used when ISNet isn't there."""
    import cv2

    rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    near = (dist <= tolerance).astype(np.uint8)
    n, labels = cv2.connectedComponents(near, connectivity=8)
    edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    edge.discard(0)  # label 0 = pixels that are NOT near the background colour
    drop = np.isin(labels, list(edge)) if edge else np.zeros((h, w), bool)
    alpha = np.where(drop, 0, 255).astype(np.uint8)
    mask = Image.fromarray(alpha, "L")
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


def cutout(img: Image.Image) -> tuple[Image.Image, str]:
    """RGBA image with the background removed, plus the method used
    ("isnet" | "border-key"). An existing alpha channel is respected: the new
    mask can only remove more, never bring back pixels that were transparent."""
    base = img.convert("RGBA")
    method = "border-key"
    mask: Image.Image | None = None
    path = model_path()
    if path.exists():
        try:
            mask = _isnet_mask(img, path)
            method = "isnet"
        except Exception as e:  # noqa: BLE001 - fall back rather than fail the request
            log.warning("ISNet background removal failed (%s); keying the border colour instead", e)
    if mask is None:
        mask = border_key_mask(img)
    old_alpha = np.asarray(base.getchannel("A"), dtype=np.uint16)
    new_alpha = (old_alpha * np.asarray(mask, dtype=np.uint16) // 255).astype(np.uint8)
    base.putalpha(Image.fromarray(new_alpha, "L"))
    return base, method
