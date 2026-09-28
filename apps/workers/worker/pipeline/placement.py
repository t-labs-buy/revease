"""Where Media-tab items land in the finished video. Pure, no I/O — the
exhaustive tests in tests/test_placement.py are the gate on changes here.

Inserted clips (intro / outro / anything between scenes) live OUTSIDE the scene
timeline: `build_timeline` still builds the body clock only from TTS durations,
and inserts are extra clips spliced between scene clips at concat time. So the
output clock is: inserts before scene 0, scene 0, inserts after scene 0, …

Overlays (logos, picture-in-picture) are composited over that finished clock
in the concat encode — never inside a scene clip — so moving a logo re-renders
zero scenes. Their time range is authored on the SOURCE clock (the editor's
preview clock, like elements and zooms), and `overlay_windows` maps it into
output seconds scene by scene: inside a scene the source window maps linearly
onto that scene's output slot (the renderer speeds footage up or holds its last
frame to fill the slot, so linear is exact at the ends and close in between).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Placed:
    """One clip in the output, in playback order."""

    kind: str  # "scene" | "insert"
    out_start_ms: int
    out_end_ms: int
    src_start_ms: int = 0  # scenes only
    src_end_ms: int = 0


def insert_slots(inserts: list[dict[str, Any]], all_step_ids: list[str],
                 rendered_step_ids: list[str]) -> list[tuple[int, dict[str, Any]]]:
    """Map each insert's `slot` (an index into the spec's full scene list, from
    editspec.effective_inserts) to a slot in the scenes actually rendered — a
    skipped or trimmed-away scene takes its inserts with the nearest rendered
    scene before it (or the very start when there is none). -1 = before the
    first rendered scene. Order is preserved."""
    rendered = {sid: i for i, sid in enumerate(rendered_step_ids)}
    out: list[tuple[int, dict[str, Any]]] = []
    for it in inserts:
        slot = int(it.get("slot", -1))
        target = -1
        for j in range(min(slot, len(all_step_ids) - 1), -1, -1):
            if all_step_ids[j] in rendered:
                target = rendered[all_step_ids[j]]
                break
        if slot >= 0 and target == -1 and it.get("position") == "end" and rendered_step_ids:
            target = len(rendered_step_ids) - 1  # an outro always follows the last scene
        out.append((target, it))
    return out


def _merge(windows: list[tuple[int, int]], gap_ms: int = 1) -> list[tuple[int, int]]:
    """Sort and merge windows that touch (within gap_ms), dropping empty ones."""
    merged: list[tuple[int, int]] = []
    for a, b in sorted(w for w in windows if w[1] > w[0]):
        if merged and a - merged[-1][1] <= gap_ms:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def overlay_windows(placed: list[Placed], rng: Any) -> list[tuple[int, int]]:
    """Output-clock windows (ms) during which an overlay is visible.

    rng: "all" -> the whole video (inserts included); "body" -> every scene,
    not the inserted clips; {"start_ms", "end_ms"} on the source clock -> the
    matching part of each scene it touches. Anything unrecognised = "all"."""
    if not placed:
        return []
    total = max(p.out_end_ms for p in placed)
    scenes = [p for p in placed if p.kind == "scene"]
    if rng == "body":
        return _merge([(p.out_start_ms, p.out_end_ms) for p in scenes])
    if isinstance(rng, dict):
        try:
            s0, s1 = int(rng.get("start_ms", 0)), int(rng.get("end_ms", 0))
        except (TypeError, ValueError):
            return []
        if s1 <= s0:
            return []
        wins = []
        for p in scenes:
            src_len = p.src_end_ms - p.src_start_ms
            a, b = max(s0, p.src_start_ms), min(s1, p.src_end_ms)
            if src_len <= 0:
                # a zero-length source window (a still) is "in range" when its
                # instant is — show the overlay for that whole scene
                if s0 <= p.src_start_ms <= s1:
                    wins.append((p.out_start_ms, p.out_end_ms))
                continue
            if b <= a:
                continue
            out_len = p.out_end_ms - p.out_start_ms
            ta = p.out_start_ms + round((a - p.src_start_ms) / src_len * out_len)
            tb = p.out_start_ms + round((b - p.src_start_ms) / src_len * out_len)
            wins.append((ta, tb))
        return _merge(wins)
    return [(0, total)]


def enable_expr(windows: list[tuple[int, int]]) -> str:
    """ffmpeg `enable=` expression for a set of output windows (ms)."""
    return "+".join(f"between(t,{a / 1000:.3f},{b / 1000:.3f})" for a, b in windows) or "0"


def overlay_box(item: dict[str, Any], dims: tuple[int, int]) -> tuple[int, int, int, int]:
    """Pixel box (x, y, w, h) for a 0..1 overlay rectangle, clamped to the frame
    and at least 8 px — the media is fitted inside it, keeping its aspect."""
    fw, fh = dims

    def f(key: str, default: float) -> float:
        try:
            return min(1.0, max(0.0, float(item.get(key, default))))
        except (TypeError, ValueError):
            return default

    w = max(8, round(f("w", 0.2) * fw))
    h = max(8, round(f("h", 0.2) * fh))
    x = min(fw - w, round(f("x", 0.0) * fw))
    y = min(fh - h, round(f("y", 0.0) * fh))
    # even sizes keep yuv420p happy after the overlay
    return max(0, x), max(0, y), w - w % 2 or 2, h - h % 2 or 2
