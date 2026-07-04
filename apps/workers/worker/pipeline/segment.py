"""Timeline segmentation: capture events + transcript (+ keyframes) -> candidate
steps. Pure functions over plain data so they are exhaustively unit-testable.

- telemetry present: split at CLICK boundaries; each step carries its click's
  target/bbox, its nearest keyframe, and the transcript span covering it. Leading
  narration (before the first click) attaches to step 1; trailing narration (after
  the last click) attaches to the final step.
- telemetry absent: fall back to transcript sentences, else scene keyframes,
  else one whole-session step.
"""

from __future__ import annotations

from typing import Any

from worker.pipeline.providers import Transcript


def _nearest_frame(t: float, keyframes: list[tuple[float, str]]) -> str | None:
    if not keyframes:
        return None
    return min(keyframes, key=lambda kf: abs(kf[0] - t))[1]


def segment(
    events: list[dict[str, Any]],
    transcript: Transcript,
    keyframes: list[tuple[float, str]],
    screenshots_by_seq: dict[int, str],
    duration_s: float,
    telemetry: str,
) -> list[dict[str, Any]]:
    clicks = sorted(
        [e for e in events if e.get("type") == "click"], key=lambda e: e.get("t_ms", 0)
    )

    if telemetry == "present" and clicks:
        return _segment_by_clicks(clicks, transcript, keyframes, screenshots_by_seq, duration_s)

    if transcript.words:
        return _segment_by_transcript(transcript, keyframes, duration_s)

    if keyframes:
        return _segment_by_scenes(keyframes, duration_s)

    return [
        {
            "action": "custom",
            "target": "Workflow",
            "selector": None,
            "bbox": None,
            "screenshot": None,
            "t_start": 0.0,
            "t_end": max(0.0, duration_s),
            "narration_span": transcript.text or "",
        }
    ]


def _segment_by_clicks(
    clicks: list[dict[str, Any]],
    transcript: Transcript,
    keyframes: list[tuple[float, str]],
    screenshots_by_seq: dict[int, str],
    duration_s: float,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    n = len(clicks)
    for i, c in enumerate(clicks):
        t_click = c.get("t_ms", 0) / 1000.0
        # Step 1 starts at 0 so leading narration is captured; others at their click.
        t_start = 0.0 if i == 0 else t_click
        if i + 1 < n:
            t_end = clicks[i + 1].get("t_ms", 0) / 1000.0
        else:
            # Final step runs to the end so trailing narration is attached.
            t_end = max(duration_s, t_click)
        shot = screenshots_by_seq.get(c.get("seq")) or _nearest_frame(t_click, keyframes)
        steps.append(
            {
                "action": "click",
                "target": (c.get("text") or c.get("selector") or "element"),
                "selector": c.get("selector"),
                "bbox": c.get("bbox"),
                "screenshot": shot,
                "t_start": round(t_start, 3),
                "t_end": round(t_end, 3),
                "narration_span": transcript.span(t_start, t_end),
            }
        )
    return steps


def _sentences(transcript: Transcript, max_words: int = 18) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    buf: list = []
    for w in transcript.words:
        buf.append(w)
        ends_sentence = w.w.endswith((".", "?", "!"))
        if ends_sentence or len(buf) >= max_words:
            out.append((buf[0].t_start, buf[-1].t_end, " ".join(x.w for x in buf).strip()))
            buf = []
    if buf:
        out.append((buf[0].t_start, buf[-1].t_end, " ".join(x.w for x in buf).strip()))
    return out


def _segment_by_transcript(
    transcript: Transcript, keyframes: list[tuple[float, str]], duration_s: float
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for t0, t1, text in _sentences(transcript):
        steps.append(
            {
                "action": "custom",
                "target": text[:80] or "Step",
                "selector": None,
                "bbox": None,
                "screenshot": _nearest_frame(t0, keyframes),
                "t_start": round(t0, 3),
                "t_end": round(max(t1, t0), 3),
                "narration_span": text,
            }
        )
    return steps


MAX_SCENE_STEPS = 20


def _segment_by_scenes(
    keyframes: list[tuple[float, str]], duration_s: float
) -> list[dict[str, Any]]:
    """Coarse scene steps for a telemetry-less, speechless upload. Capped at
    MAX_SCENE_STEPS by evenly sampling the keyframes — never one step per frame."""
    if not keyframes:
        return []
    n = min(len(keyframes), MAX_SCENE_STEPS)
    if n <= 1:
        picked = [keyframes[0]]
    else:
        idxs = [round(i * (len(keyframes) - 1) / (n - 1)) for i in range(n)]
        # de-dupe while preserving order
        seen: set[int] = set()
        picked = [keyframes[i] for i in idxs if not (i in seen or seen.add(i))]

    steps: list[dict[str, Any]] = []
    for i, (t, key) in enumerate(picked):
        t_end = picked[i + 1][0] if i + 1 < len(picked) else max(duration_s, t)
        steps.append(
            {
                "action": "custom",
                "target": f"Screen {i + 1}",
                "selector": None,
                "bbox": None,
                "screenshot": key,
                "t_start": round(t, 3),
                "t_end": round(t_end, 3),
                "narration_span": "",
            }
        )
    return steps
