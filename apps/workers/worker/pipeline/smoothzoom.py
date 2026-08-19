"""Float-precision animated zoom, replacing ffmpeg's zoompan.

zoompan positions its crop window on whole input pixels and advances the
animation once per input frame, which leaves visible stepping no matter how
much the frame is supersampled. Here every frame is warped with a float
affine matrix instead (OpenCV), so the virtual camera position is exact —
there is no quantization anywhere in the motion path.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np


def _smoothstep(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3.0 - 2.0 * p)


def apply_zoom(src: Path, dst: Path, *, scale: float, cx: float, cy: float,
               dur_s: float, ease_s: float, fps: int = 30, crf: str = "18",
               shutter: float = 0.5, blur_samples: int = 4) -> None:
    """Re-encode `src` with an ease-in / hold / ease-out zoom toward (cx, cy).

    `src` must be constant-frame-rate at `fps` (callers normalize with fps=N
    first). The zoom eases in over `ease_s`, holds at `scale`, and eases back
    out to 1x so the clip never cuts away while zoomed; on short clips each
    ramp caps at half the duration so in/out never fight over frames.

    While the zoom is MOVING, each output frame averages `blur_samples` warps
    spread across a `shutter` fraction of the frame interval (0.5 = a film
    camera's 180° shutter). Sharp 30fps frames displace many pixels per frame
    at the ramp's peak and strobe (sample-and-hold judder) no matter how exact
    the camera path is — motion blur is what reads as a smooth camera move.
    Hold frames stay perfectly sharp.
    """
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"smoothzoom: cannot open {src}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = max(1.0, float(scale))
    cx = min(1.0, max(0.0, float(cx)))
    cy = min(1.0, max(0.0, float(cy)))
    ease = max(0.2, min(float(ease_s), dur_s / 2.0))

    # Origin-anchored zoom, exactly like the editor preview's CSS
    # `transform-origin: cx cy; scale(z)`: the (cx, cy) point stays FIXED at
    # its own screen position while everything grows around it. The window
    # x0 = cx·(w − w/z) is inside the frame by construction — no clamping, so
    # the camera never swerves — and WYSIWYG with what the user tuned against.
    def progress(t: float) -> float:
        return min(_smoothstep(t / ease), _smoothstep((dur_s - t) / ease))

    def warp(frame, e: float):
        z = 1.0 + (scale - 1.0) * e
        x0 = cx * (w - w / z)
        y0 = cy * (h - h / z)
        m = np.array([[z, 0.0, -x0 * z], [0.0, z, -y0 * z]], dtype=np.float64)
        return cv2.warpAffine(frame, m, (w, h), flags=cv2.INTER_CUBIC)

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
         "-pix_fmt", "yuv420p", str(dst)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = n / fps
            es = [progress(t + k * shutter / (fps * max(1, blur_samples - 1)))
                  for k in range(blur_samples)]
            if max(es) <= 0.0005:
                out = frame  # not zoomed
            elif max(es) - min(es) < 1e-4:
                out = warp(frame, es[0])  # holding — keep it tack sharp
            else:
                acc = np.zeros((h, w, 3), dtype=np.float32)
                for e in es:
                    acc += warp(frame, e)
                out = (acc / len(es)).astype(np.uint8)
            enc.stdin.write(out.tobytes())
            n += 1
    finally:
        cap.release()
        enc.stdin.close()
        code = enc.wait()
    if code != 0:
        raise RuntimeError(f"smoothzoom: encode of {dst.name} failed (ffmpeg exit {code})")
    if n == 0:
        raise RuntimeError(f"smoothzoom: no frames decoded from {src}")
