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

# A step's on-screen window can run past where its own speech actually stopped
# (the next step's window starts right where its speech starts, so the silence
# between them lives inside the earlier step). Once that dead air exceeds this,
# split it into its own blank, editable step instead of silently absorbing it.
MIN_GAP_S = 2.0

# A step's window can start before its speech actually does — step 1's is forced
# to 0 (so leading narration is never missed), and a later step's opens at its
# triggering click, which rarely lands on the exact instant speech starts. Either
# way, anything anchored to the window's start (narration audio placement,
# source_start_ms) then thinks speech starts earlier than it really does. Split
# off gaps past this threshold into their own blank step — tighter than MIN_GAP_S
# since even a short lead-in silence is enough to misplace narration.
LEADING_GAP_S = 1.0


def _nearest_frame(t: float, keyframes: list[tuple[float, str]]) -> str | None:
    if not keyframes:
        return None
    return min(keyframes, key=lambda kf: abs(kf[0] - t))[1]


def _split_silence_gaps(
    steps: list[dict[str, Any]], transcript: Transcript, keyframes: list[tuple[float, str]]
) -> list[dict[str, Any]]:
    """Surface long silences — no spoken word for > MIN_GAP_S after a step's
    speech ends, or > LEADING_GAP_S before a step's speech starts — as their own
    blank step so they show up as an editable, empty narration row instead of
    just padding out a spoken step's clip or getting baked into where its
    narration is anchored."""
    if not transcript.words:
        return steps
    out: list[dict[str, Any]] = []
    for step in steps:
        t0, t1 = step["t_start"], step["t_end"]
        words_in = [w for w in transcript.words if t0 <= w.t_start < t1]
        if not words_in:
            # Already fully silent — one blank row already, nothing to split off.
            out.append(step)
            continue
        speech_start = words_in[0].t_start
        if speech_start - t0 > LEADING_GAP_S:
            out.append(
                {
                    "action": "custom",
                    "target": "Silence — add narration",
                    "selector": None,
                    "bbox": None,
                    "screenshot": _nearest_frame(t0, keyframes),
                    "t_start": round(t0, 3),
                    "t_end": round(speech_start, 3),
                    "narration_span": "",
                }
            )
            t0 = round(speech_start, 3)
            step = {**step, "t_start": t0}
        speech_end = words_in[-1].t_end
        gap = t1 - speech_end
        if gap > MIN_GAP_S:
            step = {**step, "t_end": round(speech_end, 3)}
            out.append(step)
            out.append(
                {
                    "action": "custom",
                    "target": "Silence — add narration",
                    "selector": None,
                    "bbox": None,
                    "screenshot": _nearest_frame(speech_end, keyframes),
                    "t_start": round(speech_end, 3),
                    "t_end": round(t1, 3),
                    "narration_span": "",
                }
            )
        else:
            out.append(step)
    return out


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
        steps = _segment_by_clicks(clicks, transcript, keyframes, screenshots_by_seq, duration_s)
        return _split_silence_gaps(steps, transcript, keyframes)

    if transcript.words:
        steps = _segment_by_transcript(transcript, keyframes, duration_s)
        return _split_silence_gaps(steps, transcript, keyframes)

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


def _sentences(transcript: Transcript, max_words: int = 60) -> list[tuple[float, float, str]]:
    """Split on real sentence boundaries, OR wherever a real pause (> MIN_GAP_S)
    separates two words even without terminal punctuation — a comma-spliced
    run-on with a long mid-utterance pause (e.g. the speaker paused to click
    something, then kept talking without a full stop) would otherwise read as
    one unbroken step, so the TTS voice reads it back-to-back with none of that
    pause and leaves the rest of the step's window silently dead. `max_words` is
    a safety valve for run-on speech with no punctuation — not a normal
    splitting rule — so a sentence is never chopped mid-thought just because it
    ran past an arbitrary word count."""
    out: list[tuple[float, float, str]] = []
    buf: list = []
    for w in transcript.words:
        if buf and w.t_start - buf[-1].t_end > MIN_GAP_S:
            out.append((buf[0].t_start, buf[-1].t_end, " ".join(x.w for x in buf).strip()))
            buf = []
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
    sentences = _sentences(transcript)
    n = len(sentences)
    steps: list[dict[str, Any]] = []
    for i, (t0, t1, text) in enumerate(sentences):
        # Stitch to the next sentence's start (like _segment_by_clicks does with
        # click times) so the silence between/around sentences stays inside a
        # segment instead of falling into a gap that never gets rendered.
        t_start = 0.0 if i == 0 else t0
        t_end = sentences[i + 1][0] if i + 1 < n else max(duration_s, t1)
        steps.append(
            {
                "action": "custom",
                "target": text[:80] or "Step",
                "selector": None,
                "bbox": None,
                "screenshot": _nearest_frame(t0, keyframes),
                "t_start": round(t_start, 3),
                "t_end": round(max(t_end, t_start), 3),
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
