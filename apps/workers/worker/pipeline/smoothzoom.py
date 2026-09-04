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
               shutter: float = 0.5, blur_samples: int = 4,
               start_s: float | None = None, end_s: float | None = None,
               windows: list[dict] | None = None) -> None:
    """Re-encode `src` with ease-in / hold / ease-out zooms toward (cx, cy).

    `src` must be constant-frame-rate at `fps` (callers normalize with fps=N
    first). Each zoom eases in over `ease_s`, holds at `scale`, and eases back
    out to 1x so the clip never cuts away while zoomed; on short windows each
    ramp caps at half the window so in/out never fight over frames.

    `start_s`/`end_s` confine the zoom to that window of the clip: flat 1x
    before `start_s`, ease in there, ease back to 1x by `end_s`. Defaults
    cover the whole clip. `windows` generalizes this to SEVERAL zooms in one
    clip — a list of {start_s, end_s, scale, cx, cy, ease_s} dicts (missing
    keys fall back to the scalar args); at any moment the window with the
    strongest ease value drives the camera, so non-overlapping windows each
    play out fully and overlaps resolve smoothly instead of fighting.

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
    if windows is None:
        windows = [{"start_s": start_s, "end_s": end_s,
                    "scale": scale, "cx": cx, "cy": cy, "ease_s": ease_s}]
    # normalize: (w0, w1, scale, cx, cy, ease) per window, clamped to the clip
    wins: list[tuple[float, float, float, float, float, float]] = []
    for win in windows:
        v0 = win.get("start_s")
        v1 = win.get("end_s")
        w0 = 0.0 if v0 is None else max(0.0, min(float(v0), dur_s))
        w1 = dur_s if v1 is None else max(w0, min(float(v1), dur_s))
        wins.append((
            w0, w1,
            max(1.0, float(win.get("scale") or scale)),
            min(1.0, max(0.0, float(win.get("cx", cx)))),
            min(1.0, max(0.0, float(win.get("cy", cy)))),
            max(0.2, min(float(win.get("ease_s") or ease_s), max(w1 - w0, 0.4) / 2.0)),
        ))

    # Origin-anchored zoom, exactly like the editor preview's CSS
    # `transform-origin: cx cy; scale(z)`: the (cx, cy) point stays FIXED at
    # its own screen position while everything grows around it. The window
    # x0 = cx·(w − w/z) is inside the frame by construction — no clamping, so
    # the camera never swerves — and WYSIWYG with what the user tuned against.
    def win_progress(win, t: float) -> float:
        w0, w1, _, _, _, ease = win
        return min(_smoothstep((t - w0) / ease), _smoothstep((w1 - t) / ease))

    def active_window(t: float):
        """The window driving the camera at `t` — the one easing strongest."""
        best, best_e = wins[0], 0.0
        for win in wins:
            e = win_progress(win, t)
            if e > best_e:
                best, best_e = win, e
        return best, best_e

    def warp(frame, e: float, win):
        _, _, wscale, wcx, wcy, _ = win
        z = 1.0 + (wscale - 1.0) * e
        x0 = wcx * (w - w / z)
        y0 = wcy * (h - h / z)
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
            win, base_e = active_window(t)
            es = [win_progress(win, t + k * shutter / (fps * max(1, blur_samples - 1)))
                  for k in range(blur_samples)]
            if max(base_e, *es) <= 0.0005:
                out = frame  # not zoomed
            elif max(es) - min(es) < 1e-4:
                out = warp(frame, es[0], win)  # holding — keep it tack sharp
            else:
                acc = np.zeros((h, w, 3), dtype=np.float32)
                for e in es:
                    acc += warp(frame, e, win)
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
