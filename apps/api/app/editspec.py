"""Edit-spec: the editable layer over a Workflow Graph. Built from the graph on
first open; the editor mutates it (script text, filler toggles, zoom nudges, scenes)
and the renderer consumes it. Shared by API (build/serve) and worker (render) so the
effective narration is computed identically on both sides."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

FILLER_WORDS = {
    "um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm", "like", "basically",
    "actually", "literally", "so", "yeah", "okay", "ok", "right",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", (text or "").strip()) if t]


def _bare(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


def detect_filler(words: list[str]) -> list[int]:
    """Indices of filler words / obvious false starts, struck by default."""
    out: list[int] = []
    for i, w in enumerate(words):
        if _bare(w) in FILLER_WORDS:
            out.append(i)
    return out


def effective_script(words: list[str], removed: list[int]) -> str:
    rm = set(removed or [])
    return " ".join(w for i, w in enumerate(words) if i not in rm).strip()


def voice_signature(spec: dict[str, Any]) -> str:
    """Content hash of what the AI-voice track depends on: each segment's spoken
    text and where it sits on the timeline. Editing the script changes this, so the
    cached preview rebuilds instead of serving stale audio."""
    payload = [
        [int(s.get("source_start_ms", 0) or 0),
         effective_script(s.get("words", []), s.get("removed", []))]
        for s in spec.get("segments", [])
    ]
    raw = json.dumps(payload, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def voice_track_key(project_id: str, voice_id: str, speed: float, spec: dict[str, Any]) -> str:
    """Storage key for the narration preview track — includes the script hash so a
    script edit yields a new key (no stale cache)."""
    return f"voicepreview/{project_id}_{voice_id}_{speed}_{voice_signature(spec)}.wav"


# Auto-zoom density: zooming every scene makes the whole video feel like it never
# stops moving. Keep at least this much SOURCE time between zoom-ins (the output
# is ~2-3x faster than the source, so this lands around one zoom every ~15-20 s
# of output), and don't bother zooming scenes too short to complete the ease-in.
# (Mirrors worker.pipeline.render.)
ZOOM_COOLDOWN_MS = 45_000
ZOOM_MIN_SCENE_MS = 1_500


def _zoom_from_bbox(bbox: Any, vw: int, vh: int) -> dict[str, Any]:
    # speed: 1 (slow ease-in) .. 5 (snappy); drives the preview transition.
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4 and vw and vh):
        return {"enabled": False, "scale": 1.6, "cx": 0.5, "cy": 0.5, "speed": 3}
    x, y, w, h = bbox
    cx = min(1.0, max(0.0, (x + w / 2) / vw))
    cy = min(1.0, max(0.0, (y + h / 2) / vh))
    # auto: derived from the click — user-tweakable in the Zoom tab (drops the flag)
    return {"enabled": True, "scale": 1.6, "cx": round(cx, 4), "cy": round(cy, 4), "speed": 3, "auto": True}


def build_edit_spec(graph_json: dict[str, Any], viewport: dict[str, int] | None) -> dict[str, Any]:
    vw = (viewport or {}).get("w", 1280)
    vh = (viewport or {}).get("h", 720)
    segments = []
    last_zoom_ms = -ZOOM_COOLDOWN_MS  # so the very first scene may zoom
    for step in graph_json.get("steps", []):
        # Script strictly from the spoken narration — no target-label fallback, so
        # a silent step has an empty script rather than invented text.
        words = tokenize(step.get("narration") or "")
        t0 = int((step.get("t_start") or 0) * 1000)
        t1 = int((step.get("t_end") or 0) * 1000)
        zoom = _zoom_from_bbox(step.get("bbox"), vw, vh)
        # throttle: a zoom on EVERY step reads as continuous zooming — keep only
        # one per cooldown window (the target stays, so it's easy to re-enable)
        if zoom["enabled"]:
            if t0 - last_zoom_ms >= ZOOM_COOLDOWN_MS and t1 - t0 >= ZOOM_MIN_SCENE_MS:
                last_zoom_ms = t0
            else:
                zoom["enabled"] = False
        segments.append(
            {
                "step_id": step["id"],
                "action": step.get("action"),
                "target": step.get("target"),
                "words": words,
                "removed": detect_filler(words),  # filler struck by default
                "zoom": zoom,
                "source_start_ms": t0,
                "source_end_ms": t1,
                "screenshot": step.get("screenshot"),
            }
        )
    return {
        "graph_version": graph_json.get("version", 1),
        "title": graph_json.get("title", "Workflow"),
        "voice": {"voice_id": "af_sarah", "speed": 1.0, "use_original": False},
        "aspect": "16:9",
        "intro": {"enabled": True, "title": graph_json.get("title", "Workflow"), "duration_ms": 2000},
        "outro": {"enabled": True, "title": "Thanks for watching", "duration_ms": 1500},
        "captions": {"enabled": True},
        # auto-zoom toward mouse/cursor activity (clicks) per scene at render time,
        # for scenes without an explicit click/user zoom. On by default.
        "motion_zoom": True,
        # product-video pacing: narrated scenes run at this tempo (1.0–1.5); silent
        # stretches are fast-forwarded by the renderer regardless.
        "pace": 1.1,
        # backdrop behind the recording (inset with padding) instead of full-bleed.
        "background": {"enabled": False, "style": "indigo"},
        "music": {"enabled": False, "storage_key": None, "gain_db": -18},
        # crop: reframe the whole video to a normalized (0..1) region (legacy single).
        "crop": {"enabled": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        # crops: multi-range reframes — each region may carry its own
        # [start_ms, end_ms] window; the first enabled match per scene wins.
        "crops": [],
        # trim: keep only the source window [start_ms, end_ms] (scene-level).
        "trim": {"enabled": False, "start_ms": 0, "end_ms": 0},
        # elements: overlay text / highlight boxes, positions normalized (0..1).
        "elements": [],
        "segments": segments,
    }


def mark_dirty(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Set per-segment `dirty` on `new` where content changed vs `old`. A voice or
    aspect change dirties every segment (re-synth / reframe)."""
    old = old or {}
    old_segs = {s.get("step_id"): s for s in old.get("segments", [])}
    global_change = (old.get("voice") != new.get("voice")) or (old.get("aspect") != new.get("aspect"))
    for seg in new.get("segments", []):
        prev = old_segs.get(seg.get("step_id"))
        changed = (
            global_change
            or prev is None
            or effective_script(prev.get("words", []), prev.get("removed", []))
            != effective_script(seg.get("words", []), seg.get("removed", []))
            or prev.get("zoom") != seg.get("zoom")
            or prev.get("source_start_ms") != seg.get("source_start_ms")
            or prev.get("source_end_ms") != seg.get("source_end_ms")
        )
        seg["dirty"] = bool(changed)
    return new
