"""buildTimeline — the one hard problem, solved first (master §Phase-4 E0).

The TTS track is shorter and re-paced than the raw recording, so original click
timestamps drift against the new audio within seconds. The fix is segment-based
reassembly: build the OUTPUT clock purely from per-step TTS durations, and for each
step map a zoom center + the raw-video source window to hold/trim into that step's
output slot.

This module is PURE (no I/O) and exhaustively unit-tested. Everything downstream
(render, captions, regenerate) depends on it, so it must never drift:
`sum(seg.out_duration_ms) == total`, by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class StepInput:
    """One workflow step feeding the timeline."""

    step_id: str
    tts_duration_ms: int  # d'[step] — authoritative output duration for this step
    source_start_ms: int = 0  # raw-video window for this step (from the graph)
    source_end_ms: int = 0
    click_x: float | None = None  # click coordinate in viewport pixels
    click_y: float | None = None
    viewport_w: int | None = None
    viewport_h: int | None = None
    zoom_enabled: bool = True
    zoom_scale: float = 1.6


@dataclass
class Segment:
    step_id: str
    index: int
    out_start_ms: int
    out_end_ms: int
    out_duration_ms: int
    source_start_ms: int
    source_end_ms: int
    speed: float  # source_len / out_len; 1.0 when holding a freeze frame
    hold: bool  # True => freeze the first source frame for the whole slot
    zoom: dict[str, float] | None  # {cx, cy, scale} normalized+clamped, or None


@dataclass
class Timeline:
    segments: list[Segment] = field(default_factory=list)
    total_duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_duration_ms": self.total_duration_ms,
            "segments": [s.__dict__ for s in self.segments],
        }


def build_timeline(steps: list[StepInput], default_scale: float = 1.6) -> Timeline:
    """Map steps -> output segments. The output clock is the cumulative sum of
    per-step TTS durations, so audio and video can never drift."""
    segments: list[Segment] = []
    cursor = 0
    for i, s in enumerate(steps):
        out_dur = max(0, int(s.tts_duration_ms))
        out_start = cursor
        out_end = cursor + out_dur
        cursor = out_end

        # Normalize the source window (defensive: handle reversed / negative).
        src_start = max(0, min(s.source_start_ms, s.source_end_ms))
        src_end = max(s.source_start_ms, s.source_end_ms)
        src_len = src_end - src_start

        if src_len <= 0 or out_dur <= 0:
            # Back-to-back clicks (no window) or a zero-duration step: freeze-frame,
            # never divide by zero.
            hold = True
            speed = 1.0
        else:
            hold = False
            speed = src_len / out_dur  # >1 = play faster to fit; <1 = slow to fill

        zoom: dict[str, float] | None = None
        if (
            s.zoom_enabled
            and s.click_x is not None
            and s.click_y is not None
            and s.viewport_w
            and s.viewport_h
        ):
            cx = _clamp(s.click_x / s.viewport_w, 0.0, 1.0)  # clamps out-of-bounds coords
            cy = _clamp(s.click_y / s.viewport_h, 0.0, 1.0)
            zoom = {
                "cx": round(cx, 4),
                "cy": round(cy, 4),
                "scale": max(1.0, float(s.zoom_scale or default_scale)),
            }

        segments.append(
            Segment(
                step_id=s.step_id,
                index=i,
                out_start_ms=out_start,
                out_end_ms=out_end,
                out_duration_ms=out_dur,
                source_start_ms=src_start,
                source_end_ms=src_end,
                speed=round(speed, 6),
                hold=hold,
                zoom=zoom,
            )
        )

    return Timeline(segments=segments, total_duration_ms=cursor)
