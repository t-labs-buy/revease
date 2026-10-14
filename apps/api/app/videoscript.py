"""Narration written from the whole recording — the way it works when someone
drops the video into a chat with Claude.

Why this exists next to rewrite.generate_script: the per-scene Generate writes
one line into each scene the segmenter already cut, from one frame per scene.
For a silent upload those scenes are coarse screen-change guesses ("Screen 3",
nine seconds long), so the model never sees the suite name being typed or the
dropdown opening, and five word-capped slots cannot carry a thirteen-beat
walkthrough. Here the model is shown the recording's stored keyframes (about
one a second, each labelled with its time) and writes as many lines as the
footage has moments, each with the time it starts.

The output is a timed script in the same `[m:ss.s] line` form a user can paste,
so the ordinary Apply-script path (worker scriptalign) places the lines and
rebuilds the scenes around them: the model's cuts become the scenes, and
nothing here touches the graph. A recording with clicks keeps its click scenes
and the script is spread across them, as Apply script already does.

Long recordings: one vision call carries at most FRAMES_PER_CALL images (about
350 input tokens a frame), so the keyframes are split into contiguous windows
written one after another, each shown the last lines of the previous window so
the voiceover reads as one piece and the hook is written once. Windowing,
parsing and joining are pure; the only I/O is `write_window`'s model call.

Two modes. "fit" keeps every line inside the footage it covers, using the
words-per-second budget the per-scene Generate uses (the render freezes the
last frame while a voice runs over), with the same shorten-then-trim pass.
"free" sets no limit: the editor's fit-narration tools pace the video to the
voice afterwards.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass

from app.llm import complete_vision
from app.rewrite import enforce_budgets, json_values, scene_word_budget
from app.tracing import observe

log = logging.getLogger("refract.videoscript")

# Images per vision call. 60 one-second frames at 768px is ~21k input tokens
# and ~40s of model time; more per call buys little and risks the context.
FRAMES_PER_CALL = 60
# A line the model dates before the previous one is moved up, not dropped.
MIN_STEP_S = 0.5


@dataclass
class TimedLine:
    t: float  # source-clock seconds where the line starts
    text: str
    t_end: float | None = None  # set only to close the line's scene early (at a cut)


def plan_windows(keyframes: list[tuple[float, str]], per_call: int = FRAMES_PER_CALL) -> list[list[tuple[float, str]]]:
    """Contiguous, near-equal windows of at most `per_call` keyframes, in time
    order. Every stored frame is sent exactly once: a ten-minute recording at
    one frame a second is ten calls of sixty."""
    if not keyframes:
        return []
    n = max(1, math.ceil(len(keyframes) / max(1, per_call)))
    size = math.ceil(len(keyframes) / n)
    return [keyframes[i:i + size] for i in range(0, len(keyframes), size)]


def window_bounds(windows: list[list[tuple[float, str]]], duration_s: float) -> list[tuple[float, float]]:
    """(t0, t1) each window covers: from its first frame (the recording's start
    for the first) to the next window's first frame (the end for the last)."""
    out = []
    for i, win in enumerate(windows):
        t0 = 0.0 if i == 0 else win[0][0]
        t1 = windows[i + 1][0][0] if i + 1 < len(windows) else max(duration_s, win[-1][0])
        out.append((t0, t1))
    return out


VIDEO_SYSTEM = (
    "You write the voiceover for a screen recording of a software product, the way a "
    "presenter would after watching it. You are shown frames sampled from the recording in "
    "order, each labelled with its time in seconds. Study what changes from frame to frame: "
    "pages opening, menus, fields being filled, buttons pressed, lists loading. Then write the "
    "narration as a sequence of lines, each starting at the moment the recording begins to "
    "show what it describes.\n\n"
    "The author's brief in the message is the top instruction. Where it asks for a language, "
    "a tone, an audience, a focus, things to mention or leave out, a length, or different "
    "content, it overrides every rule below. The rules only fill in what the brief does not say.\n\n"
    "Rules:\n"
    "- Open with one short hook, at most fifteen words, that names the product or task and "
    "what the viewer gets, and close with one short line on the result. Write the hook only "
    "in the first part of a recording and the close only in the last part (you are told which "
    "part this is). Never open with 'In this video we will' or 'Welcome to'.\n"
    "- Keep lines short: most lines six to twelve words, never more than twenty. One action "
    "per line. Tell the viewer what to do in the imperative ('Click Save.', 'Give the report "
    "a name.', 'Choose a folder.'), not what they are doing ('You give the report a name'). "
    "A short reason may follow as its own sentence.\n"
    "- Do not describe what a page or dialog contains (its columns, its steps, its fields) "
    "unless that is the point; say what to do there.\n"
    "- Write the step, not the frame. You are shown far more frames than there are steps: a "
    "dialog opening, a field being clicked, a value typed and the list closing are ONE step, "
    "narrated once. A line every three to six seconds of footage is the normal pace; never a "
    "line per frame. A frame where nothing new happens (a page sitting there, a cursor "
    "moving) gets no line.\n"
    "- Say what a step is for, not the sample data: name the field or control and the kind of "
    "value it takes. Do not read out typed test values, every entry of a list, or the exact "
    "item picked unless the viewer needs it. A list of options is worth naming only when the "
    "options are the point.\n"
    "- Narrate what is visible: name the pages, menus, buttons and fields you can actually read "
    "in the frames. Never describe UI, data or outcomes you cannot see. Keep product and "
    "feature names exactly as they appear on screen.\n"
    "- Spoken style: present tense, plain words, light connectors ('First', 'Next', 'Then', "
    "'That's it') so the lines flow as one walkthrough rather than a list of captions.\n"
    "- TTS-safe: plain spoken words only; no markdown, emojis, parentheses, stage directions "
    "or camera notes. Expand abbreviations that are awkward aloud; keep numbers easy to say.\n"
    "- Banned: 'simply', 'just', 'easy', 'basically', 'as you can see', 'go ahead', 'here you "
    "are on', 'logged in and ready'.\n"
    "- Start times are seconds on the recording's clock, never decreasing, and inside the "
    "range of the part you are writing."
)

# Spoken pace the two modes aim at, in words per second of footage. "fit" is
# the render's own budget (rewrite.BUDGET_WORDS_PER_S, with the scene gap);
# "free" is how a presenter actually narrates a demo — a little faster than
# real time, which the editor's fit tools then absorb — not "as much as the
# model feels like", which produced 352 words for 35 seconds of footage.
FIT_WORDS_PER_S = 2.3
FREE_WORDS_PER_S = 3.0
FREE_MAX_WORDS_PER_S = 4.0
# A presenter's demo script lands a short line about every three seconds.
LINE_EVERY_S = 3.0


def mode_note(mode: str, seconds: float) -> str:
    """The length instruction for one part of `seconds` of footage — stated as
    numbers of words and lines for that part, so a long recording keeps the
    same pace in each of its windows."""
    seconds = max(1.0, float(seconds))
    lines = max(1, round(seconds / LINE_EVERY_S))
    if mode == "free":
        return (
            f"Length: this part is {seconds:.0f} seconds of footage, so write about "
            f"{int(seconds * FREE_WORDS_PER_S)} words in total and never more than "
            f"{int(seconds * FREE_MAX_WORDS_PER_S)}, in roughly {lines} lines. There is no cap "
            "on a single line; the editor paces the video to the voice afterwards."
        )
    return (
        f"Timing: a voice speaks about {FIT_WORDS_PER_S} words a second. This part is "
        f"{seconds:.0f} seconds of footage, so at most {int(seconds * FIT_WORDS_PER_S)} words in "
        f"total, in roughly {lines} lines. Each line must also fit the footage from its start "
        f"to the next line's start (or the end of this part): never more words than "
        f"{FIT_WORDS_PER_S} times that gap in seconds."
    )


def window_parts(
    frames: list[tuple[float, bytes]],
    *,
    t0: float,
    t1: float,
    duration_s: float,
    index: int,
    count: int,
    title: str,
    brief: str,
    mode: str,
    prior: list[TimedLine],
) -> list[str | bytes]:
    """The user turn for one window: context text, the labelled frames, the ask."""
    mode = mode if mode in ("fit", "free") else "fit"
    head = (
        f'Video title: "{title}".\n'
        f"About this video (from the author — follow it): {brief}\n\n"
        f"The recording is {duration_s:.1f} seconds long. This is part {index + 1} of {count}, "
        f"covering {t0:.1f}s to {t1:.1f}s."
    )
    if prior:
        head += (
            "\n\nLines already written for the earlier parts — continue after them, do not repeat "
            "them and do not write another hook:\n"
            + json.dumps([{"t": round(ln.t, 1), "line": ln.text} for ln in prior], ensure_ascii=False)
        )
    head += "\n\n" + mode_note(mode, t1 - t0) + "\n\nFrames, in order:"
    parts: list[str | bytes] = [head]
    for t, img in frames:
        parts += [f"t={t:.1f}s", img]
    # The brief again after the frames: an instruction sitting before sixty
    # images carries far less weight than one next to the question.
    parts.append(
        f"Author's brief — follow it over every other rule: {brief}\n\n"
        "Reply with ONLY a JSON array (no prose, no code fences) of objects "
        '{"t": <start seconds>, "line": "<narration>"}, in time order.'
    )
    return parts


def _seconds(v: object) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().rstrip("s")
        try:
            total = 0.0
            for part in s.split(":"):
                total = total * 60 + float(part)
            return total
        except ValueError:
            return None
    return None


def parse_timed(text: str) -> list[TimedLine]:
    """Timed lines from a model reply. Tolerant by design: one array, several
    arrays on separate lines, bare objects, a `time`/`start` key instead of `t`,
    `text`/`narration` instead of `line`, or a `m:ss` string for the time all
    parse. Items without usable text are skipped; a missing time becomes None
    and is filled in by join_lines."""
    items: list = []
    for val in json_values(text):
        if isinstance(val, list):
            items += val
        elif isinstance(val, dict):
            items.append(val)
    out: list[TimedLine] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        line = next((it[k] for k in ("line", "text", "narration") if isinstance(it.get(k), str)), "")
        line = " ".join(line.split())
        if not line:
            continue
        t = next((_seconds(it[k]) for k in ("t", "time", "start", "start_s") if k in it), None)
        out.append(TimedLine(t if t is not None else float("nan"), line))
    return out


def join_lines(parts: list[list[TimedLine]], duration_s: float) -> list[TimedLine]:
    """One ordered script from the windows' replies: times clamped to the
    recording, made non-decreasing (a line dated earlier than the previous is
    moved to just after it), undated lines placed right after their predecessor."""
    out: list[TimedLine] = []
    prev = -MIN_STEP_S
    for part in parts:
        for ln in part:
            t = ln.t
            if t != t or t < 0:  # NaN: the model gave no time
                t = prev + MIN_STEP_S if out else 0.0
            t = min(max(0.0, t), max(0.0, duration_s))
            if out and t < prev + MIN_STEP_S:
                t = min(prev + MIN_STEP_S, max(0.0, duration_s))
            out.append(TimedLine(round(t, 1), ln.text))
            prev = out[-1].t
    if out:
        out[0].t = 0.0
    return out


# Kept footage within this much of the whole recording is "untrimmed": the
# segmenter's windows end a few ms short of the duration, which is no trim.
UNTRIMMED_TOLERANCE_MS = 250
# Scene windows this close together are one continuous stretch of footage.
JOIN_GAP_MS = 3


def kept_ranges(spec: dict | None, duration_ms: int) -> list[list[int]] | None:
    """The source footage the editor still shows, from the edit spec: the
    windows of the scenes that are not skipped, joined where they touch, cut to
    the spec-level trim. None when that is the whole recording.

    Why: a trim made in the editor lives in the spec (scene windows, skipped
    scenes), not on the recording. A Generate that rebuilds the scenes would
    migrate the spec onto new scenes and lose it — and had already shown the
    model the footage the user cut. The job stores these ranges on the session
    as keep ranges, the same thing the Prepare page writes, so the rebuilt
    scenes cover only the kept footage."""
    if not spec or duration_ms <= 0:
        return None
    wins = sorted(
        (int(s.get("source_start_ms") or 0), int(s.get("source_end_ms") or 0))
        for s in spec.get("segments", []) if not s.get("skipped")
    )
    trim = spec.get("trim") or {}
    if trim.get("enabled") and int(trim.get("end_ms") or 0) > int(trim.get("start_ms") or 0):
        lo, hi = int(trim["start_ms"]), int(trim["end_ms"])
        wins = [(max(a, lo), min(b, hi)) for a, b in wins]
    merged: list[list[int]] = []
    for a, b in wins:
        if b <= a:
            continue
        if merged and a <= merged[-1][1] + JOIN_GAP_MS:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if not merged:
        return None
    kept = sum(b - a for a, b in merged)
    if len(merged) == 1 and kept >= duration_ms - UNTRIMMED_TOLERANCE_MS and merged[0][0] <= UNTRIMMED_TOLERANCE_MS:
        return None
    return merged


# A line the model dates this soon after removed footage starts where the kept
# footage resumes: the model saw the first frame after the cut, not the cut.
SNAP_TO_CUT_S = 3.0


def align_to_ranges(lines: list[TimedLine], spans: list[tuple[float, float]]) -> list[TimedLine]:
    """Keep every scene inside the kept footage. The lines are written as pinned
    times, and scriptalign never moves a pin — so a line dated 31 s with a cut
    at 20–30 s would open a scene spanning 0–31 s, and the render (which knows
    nothing of cuts) would play the removed ten seconds. For each gap between
    kept spans: a line dated inside it moves to where footage resumes; the
    first line after it moves onto that edge when it is within SNAP_TO_CUT_S;
    otherwise the line before the gap closes at the cut and the footage up to
    the next line becomes a blank scene (scriptalign's end-time rule)."""
    if not lines or len(spans) < 2:
        return lines
    out = [TimedLine(ln.t, ln.text, ln.t_end) for ln in lines]
    gaps = [(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1) if spans[i + 1][0] > spans[i][1]]
    for g0, g1 in gaps:
        for ln in out:
            if g0 < ln.t < g1:
                ln.t = g1
        after = next((ln for ln in out if ln.t >= g1), None)
        before = next((ln for ln in reversed(out) if ln.t < g0), None)
        if after is not None and after.t - g1 <= SNAP_TO_CUT_S:
            after.t = g1
        elif before is not None:
            before.t_end = g0
    out.sort(key=lambda ln: ln.t)
    return out


def _stamp(t: float) -> str:
    tenths = int(round(max(0.0, t) * 10))
    h, rem = divmod(tenths, 36000)
    m, rem = divmod(rem, 600)
    s = rem / 10
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m}:{s:04.1f}"


def timed_script_text(lines: list[TimedLine]) -> str:
    """`[m:ss.s] line` per line — exactly what scriptalign.parse_script pins
    on, so the generated script travels the same road as a pasted one."""
    def stamp(ln: TimedLine) -> str:
        if ln.t_end is not None and ln.t_end > ln.t:
            return f"[{_stamp(ln.t)} - {_stamp(ln.t_end)}]"
        return f"[{_stamp(ln.t)}]"

    return "\n".join(f"{stamp(ln)} {ln.text}" for ln in lines if ln.text.strip())


def fit_lines(lines: list[TimedLine], duration_s: float, speed: float = 1.0) -> list[TimedLine]:
    """"fit" mode: each line's footage is the gap to the next start; lines over
    that budget get the shorten-then-trim pass. The last line's footage runs to
    the end of the recording."""
    if not lines:
        return lines
    limits: list[int | None] = []
    for i, ln in enumerate(lines):
        end = lines[i + 1].t if i + 1 < len(lines) else max(duration_s, ln.t)
        if ln.t_end is not None:
            end = min(end, ln.t_end)  # the scene closes at a cut
        limits.append(scene_word_budget(end - ln.t, speed))
    texts = enforce_budgets([ln.text for ln in lines], limits)
    return [TimedLine(ln.t, txt, ln.t_end) for ln, txt in zip(lines, texts)]


@observe(name="ai-video-script-window")
def write_window(frames: list[tuple[float, bytes]], **ctx) -> list[TimedLine]:
    """One vision call for one window; `ctx` is window_parts' keyword set. A
    reply with no usable line is asked for once more with a nudge."""
    parts = window_parts(frames, **ctx)
    for attempt in range(2):
        text = complete_vision(VIDEO_SYSTEM, parts, max_tokens=16000, timeout=240)
        lines = parse_timed(text)
        if lines:
            return lines
        log.warning("video script reply unusable (attempt %d): %.200s", attempt + 1, text)
        parts = [*parts, "Your previous answer held no usable lines. Reply with the JSON array only."]
    raise ValueError("the AI reply could not be read as narration lines")
