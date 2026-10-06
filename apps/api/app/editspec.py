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


# Pause marker: one whitespace-free token inside a scene's words, e.g.
# `[pause:1.5]`. Being a single token it survives tokenize / filler indices /
# merge / split untouched; the worker voices the text around it and inserts that
# much silence. Clamped so a typo can't stall a scene for a minute.
PAUSE_RE = re.compile(r"\[pause:(\d+(?:\.\d+)?)\]", re.IGNORECASE)
PAUSE_MIN_S = 0.2
PAUSE_MAX_S = 3.0


def split_pauses(script: str) -> list[str | float]:
    """A script as alternating spoken chunks (str) and pauses (seconds, float),
    in order. A script with no marker is one chunk — callers rely on that to keep
    the marker-free path byte-identical."""
    parts: list[str | float] = []
    pos = 0
    script = script or ""
    for m in PAUSE_RE.finditer(script):
        text = script[pos : m.start()].strip()
        if text:
            parts.append(text)
        parts.append(min(PAUSE_MAX_S, max(PAUSE_MIN_S, float(m.group(1)))))
        pos = m.end()
    tail = script[pos:].strip()
    if tail:
        parts.append(tail)
    return parts


def spoken_text(script: str) -> str:
    """The script as prose: pause markers removed. For captions, documents,
    titles and LLM prompts — anywhere the marker would be read as text."""
    return " ".join(PAUSE_RE.sub(" ", script or "").split())


def voice_signature(spec: dict[str, Any]) -> str:
    """Content hash of what the AI-voice track (and its pacing timeline) depends
    on: each segment's spoken text, its source window, and whether it's in the
    mix at all. Editing the script, trimming a segment, toggling skip, or
    changing the global pace all change this, so the cached preview rebuilds
    instead of serving stale audio or stale pacing."""
    payload = [
        [int(s.get("source_start_ms", 0) or 0), int(s.get("source_end_ms", 0) or 0),
         bool(s.get("skipped")), effective_script(s.get("words", []), s.get("removed", []))]
        for s in spec.get("segments", [])
    ]
    raw = json.dumps([payload, spec.get("pace"), spec.get("trim")], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def voice_track_key(project_id: str, voice_id: str, speed: float, spec: dict[str, Any]) -> str:
    """Storage key for the narration preview track — includes the script hash so a
    script edit yields a new key (no stale cache)."""
    return f"voicepreview/{project_id}_{voice_id}_{speed}_{voice_signature(spec)}.wav"


def voice_timeline_key(project_id: str, voice_id: str, speed: float, spec: dict[str, Any]) -> str:
    """Storage key for the preview track's pacing timeline (build_timeline's
    per-segment out_start_ms/speed/hold) — same signature as the audio itself,
    so the two can never point at mismatched content."""
    return f"voicepreview/{project_id}_{voice_id}_{speed}_{voice_signature(spec)}.json"


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
    # Off by default: the click position is kept as the zoom target so the user
    # can switch it on per scene in the Zoom tab and it already aims right.
    # auto: derived from the click — user-tweakable in the Zoom tab (drops the flag)
    return {"enabled": False, "scale": 1.6, "cx": round(cx, 4), "cy": round(cy, 4), "speed": 3, "auto": True}


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
        # intro/outro cards and automatic zooms are opt-in: a new project renders
        # the plain recording until the user turns them on in the editor.
        "intro": {"enabled": False, "title": graph_json.get("title", "Workflow"), "duration_ms": 2000},
        "outro": {"enabled": False, "title": "Thanks for watching", "duration_ms": 1500},
        "captions": {"enabled": True},
        # auto-zoom toward mouse/cursor activity (clicks) per scene at render time,
        # for scenes without an explicit click/user zoom. Off by default.
        "motion_zoom": False,
        # pace: uniform tempo (1.0–1.5) applied to every scene, narrated or
        # silent alike. 1.0 = original speed, full source length kept.
        "pace": 1.0,
        # backdrop behind the recording (inset with padding) instead of full-bleed.
        "background": {"enabled": False, "style": "indigo"},
        "music": {"enabled": False, "storage_key": None, "gain_db": -18, "duck": True,
                  "fade_in_ms": 1000, "fade_out_ms": 2000, "start_ms": 0},
        # inserts: full-screen clips / images / title cards played between scenes
        # (start = intro, end = outro). They sit OUTSIDE the scene timeline — see
        # effective_inserts. overlays: picture-in-picture images/videos (logos)
        # composited over the finished video, never part of a scene's hash.
        "inserts": [],
        "overlays": [],
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


INSERT_TYPES = ("image", "video", "title")


def effective_inserts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The full-screen clips to play around the scenes, in playback order:
    every `start` insert, then each `after:<step_id>` insert in scene order, then
    every `end` insert. Each returned item carries `slot`: -1 = before the first
    scene, i = after scene i (end inserts share the last scene's slot, after its
    own inserts).

    Legacy `intro` / `outro` cards (the old Intro tab) become start / end inserts
    while enabled, unless an insert with id "intro" / "outro" already replaced
    them — so projects saved before the Media tab render exactly as before.
    An `after:` step that no longer exists (reprocess renumbered, scene deleted)
    falls to just before the end inserts instead of vanishing.

    Pure: shared by the API, the worker and (ported) the web preview, so all
    three agree on order and total duration."""
    segs = spec.get("segments") or []
    n = len(segs)
    slot_of = {s.get("step_id"): i for i, s in enumerate(segs)}
    items: list[dict[str, Any]] = [dict(x) for x in spec.get("inserts") or [] if isinstance(x, dict)]
    ids = {x.get("id") for x in items}
    for which, pos in (("intro", "start"), ("outro", "end")):
        card = spec.get(which) or {}
        if card.get("enabled") and which not in ids:
            media = card.get("media_key")
            legacy = {"id": which, "position": pos, "duration_ms": int(card.get("duration_ms") or 2000),
                      "legacy": True}
            if media:
                legacy.update(type=card.get("media_type") or "image", media_key=media, keep_audio=True)
            else:
                legacy.update(type="title", title=str(card.get("title") or ""))
            items.insert(0, legacy) if pos == "start" else items.append(legacy)

    # sort key (slot, band, order): start inserts sit in slot -1; an insert after
    # scene i in slot i; end inserts after the last scene's own inserts (band 2),
    # orphans just before them (band 1 in the last slot).
    keyed: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
    for order, it in enumerate(items):
        if it.get("type") not in INSERT_TYPES:
            continue
        if it.get("type") != "title" and not it.get("media_key"):
            continue
        pos = str(it.get("position") or "end")
        if pos == "start":
            slot, band = -1, 0
        elif pos.startswith("after:"):
            slot, band = slot_of.get(pos[6:], n - 1), 1
        else:
            slot, band = n - 1, 2
        keyed.append(((slot, band, order), {**it, "slot": slot}))
    keyed.sort(key=lambda t: t[0])
    return [it for _, it in keyed]


def insert_duration_ms(item: dict[str, Any], media_ms: int | None = None) -> int:
    """How long an insert plays. A video plays its trimmed length (the whole clip
    when untrimmed and `media_ms` is known); images and title cards their
    `duration_ms`. Never below half a second."""
    if item.get("type") == "video":
        t0 = int(item.get("trim_start_ms") or 0)
        t1 = item.get("trim_end_ms")
        if t1:
            return max(500, int(t1) - t0)
        if media_ms:
            return max(500, int(media_ms) - t0)
    return max(500, int(item.get("duration_ms") or 2000))
