"""The one place the understanding pipeline LOOKS at the recording.

Everything else in the pipeline works from clicks and spoken words. When the
user supplied a script for a recording with neither, the question "where on the
video does each line begin?" is put to a vision model shown sampled keyframes.
scriptalign.py turns the answer into windows and holds the offline fallback.

Best-effort by contract: no key, a bad reply, missing frames or any exception
returns None and the caller carries on with proportional timing. That is what
keeps the test suite offline and a provider outage from failing a run.

Writing narration from frames is deliberately NOT done here: the pipeline never
invents text, so processing a recording costs no tokens the user did not ask
for. That is the editor's Generate button (app.rewrite.generate_script with
frames), which runs only when pressed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.editspec import spoken_text
from app.frames import frame_jpeg
from app.llm import NoLLMConfigured, complete_vision, has_llm
from app.tracing import observe as _observe
from worker.pipeline.scriptalign import ScriptLine, valid_starts

log = logging.getLogger("refract.pipeline.scriptvision")

MAX_FRAMES = 48


def pick_frames(
    keyframes: list[tuple[float, str]], cuts: list[float], max_frames: int = MAX_FRAMES
) -> list[tuple[float, str]]:
    """Up to `max_frames` keyframes: the first frame after each scene change (the
    moments worth seeing), topped up with an even spread so long static stretches
    are still represented. Pure; returned in time order."""
    if len(keyframes) <= max_frames:
        return list(keyframes)
    chosen: dict[int, None] = {0: None, len(keyframes) - 1: None}
    for c in cuts:
        i = next((j for j, (t, _) in enumerate(keyframes) if t >= c), None)
        if i is not None:
            chosen.setdefault(i)
    idxs = sorted(chosen)
    if len(idxs) > max_frames:  # more cuts than budget: thin them evenly
        idxs = [idxs[round(i * (len(idxs) - 1) / (max_frames - 1))] for i in range(max_frames)]
    else:
        spare = max_frames - len(idxs)
        for i in range(spare):
            chosen.setdefault(round((i + 0.5) * (len(keyframes) - 1) / spare))
        idxs = sorted(chosen)[:max_frames]
    return [keyframes[i] for i in sorted(set(idxs))]


def _parse_array(content: str, n: int) -> list[Any]:
    t = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    arr = json.loads(t)
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError(f"expected {n} items, got {len(arr) if isinstance(arr, list) else '?'}")
    return arr


ALIGN_SYSTEM = (
    "You align a written narration script to a silent screen recording. You are shown "
    "frames sampled from the recording, each labelled with its time in seconds, followed "
    "by the script's lines in order. For every line, decide the time at which the "
    "recording starts showing what that line talks about. Lines are narrated in order, so "
    "the start times must never decrease. A line with a fixed time keeps exactly that "
    "time. The first line starts at the first moment of the recording."
)


@_observe(name="script-align-vision")
def align_starts(
    lines: list[ScriptLine],
    keyframes: list[tuple[float, str]],
    cuts: list[float],
    duration_s: float,
) -> list[float] | None:
    """Source-clock start (seconds) for each line, or None when unavailable."""
    if not lines or not keyframes or not has_llm():
        return None
    try:
        parts: list[str | bytes] = [f"The recording is {duration_s:.1f} seconds long. Frames, in order:"]
        shown = 0
        for t, key in pick_frames(keyframes, cuts):
            img = frame_jpeg(key)
            if img is not None:
                parts += [f"t={t:.1f}s", img]
                shown += 1
        if shown < 2:
            return None
        script = [
            {"line": i + 1, "text": spoken_text(ln.text),
             **({"fixed_time": round(ln.t_start, 2)} if ln.t_start is not None else {})}
            for i, ln in enumerate(lines)
        ]
        ask = (
            f"Script ({len(lines)} lines):\n" + json.dumps(script, ensure_ascii=False)
            + f"\n\nReply with ONLY a JSON array of exactly {len(lines)} numbers (no prose, no "
            "code fences): the start time in seconds of each line, in order, non-decreasing, "
            f"between 0 and {duration_s:.1f}."
        )
        for attempt in range(2):
            text = complete_vision(ALIGN_SYSTEM, [*parts, ask], max_tokens=4000 + 40 * len(lines))
            try:
                starts = _parse_array(text, len(lines))
            except ValueError:
                starts = None
            if starts is not None and valid_starts(starts, len(lines), duration_s):
                return [float(s) for s in starts]
            log.warning("vision alignment reply unusable (attempt %d)", attempt + 1)
            ask += "\n\nYour previous answer was not a valid non-decreasing array of that length. Try again."
    except NoLLMConfigured:
        return None
    except Exception as e:
        log.warning("vision alignment failed (%s); using proportional timing", e)
    return None
