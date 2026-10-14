"""Script alignment: a user-written script -> candidate steps with source windows.

A recording without a voiceover has nothing for Whisper to time, so when the user
supplies a script the SCRIPT defines the scenes (one per line) and the only thing
left to compute is which stretch of video each line owns. The output clock needs
no help: a scene's output length is its TTS duration, and the renderer speeds the
footage up or freezes its last frame to fit (see timeline.py / render.py).

Each line's start is chosen in layers, most trusted first:

1. a timestamp the user wrote (`[mm:ss] text`, `mm:ss text`, an SRT cue) pins it;
2. start times from the vision model (scriptvision.align_starts), when valid;
3. otherwise its cumulative share of the words — a line twice as long gets twice
   the footage, so every scene ends up retimed by about the same factor;
4. unpinned starts then snap to the nearest real scene change, because a boundary
   that lands mid-screen is the visible failure mode of 2 and 3.

Windows are a contiguous, in-order partition of the KEPT video (trim / keep
ranges): no footage is orphaned and no line lands in a removed region. A first
line pinned later than the start gets a blank lead-in step before it, so the pin
is honoured without dropping the opening footage; likewise an END time the user
wrote (`[0:03 - 0:06]`, an SRT cue) closes that scene there, and the footage up
to the next line becomes a blank scene — so a timed script never has a line
stretched over footage it was not written for.

Pure functions over plain data, no I/O — the same rule as segment.py, and the
reason tests/test_scriptalign.py can cover the edge cases exhaustively.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.editspec import spoken_text

# Sentences shorter than this are packed into their neighbour: "Great." is not a scene.
MIN_LINE_WORDS = 4
# No scene shorter than this — also bounds how many lines a short video can carry.
MIN_SCENE_S = 1.0
# How far a boundary may move to land on a scene change, and the share of the
# shorter neighbouring scene it may consume doing so.
SNAP_MAX_S = 2.0
SNAP_SHARE = 0.4
# A first line pinned later than this gets a blank lead-in step.
LEAD_IN_S = 1.0
# A user-written end time only splits off a blank scene when the footage left
# before the next line is at least this long; a few hundred ms is rounding.
GAP_MIN_S = 0.5
# Matches segment.py's silence steps, so the editor treats both alike.
BLANK_TARGET = "Silence — add narration"

_SRT_TIME = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_SRT_CUE = re.compile(rf"^\s*{_SRT_TIME}\s*-->\s*{_SRT_TIME}.*$")
_T = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?"
def _range(n: int) -> str:  # `start`, or `start - end`, as groups s<n> / e<n>
    return rf"(?P<s{n}>{_T})(?:\s*[-–—]\s*(?P<e{n}>{_T}))?"


# `[1:02]`, `[0:00 - 0:03]`, `(1:02)`, or a bare `1:02` / `1:02 - 1:05` followed
# by a separator. The start pins the line; an end, when given, closes its
# scene (see script_steps — the footage up to the next line becomes a blank).
_STAMP = re.compile(
    r"^\s*(?:\[\s*" + _range(1) + r"\s*\]|\(\s*" + _range(2) + r"\s*\)"
    r"|" + _range(3) + r"(?=\s|[-–—:|]))\s*[-–—:|]?\s*"
)

_INLINE_STAMP = re.compile(rf"[ \t]*(\[\s*{_T}(?:\s*[-–—]\s*{_T})?\s*\])")
_COLUMNS = re.compile(r"\t+|\s*\|\s*")
_QUOTES = "\"'“”‘’"


def _cell_text(raw: str) -> str:
    """The narration cell of a table row. A storyboard pasted from a doc or a
    spreadsheet arrives as `time ⇥ what's on screen ⇥ "voiceover"`: the last
    non-empty column is the voiceover, and its quotes are typography."""
    cells = [c.strip() for c in _COLUMNS.split(raw) if c.strip()]
    s = cells[-1] if cells else raw.strip()
    return s.strip(_QUOTES).strip()


def _is_header(raw: str) -> bool:
    """A column-header row (`Time ⇥ On screen ⇥ Voiceover`): several short
    cells, no digits, no sentence punctuation."""
    cells = [c.strip() for c in _COLUMNS.split(raw) if c.strip()]
    return (
        len(cells) >= 2
        and not any(ch.isdigit() for ch in raw)
        and not any(ch in ".!?" for ch in raw)
        and all(len(c.split()) <= 3 for c in cells)
    )


@dataclass
class ScriptLine:
    text: str
    t_start: float | None = None  # seconds on the source clock when the user pinned it
    t_end: float | None = None  # where the user said the line's footage ends, if given


def _clock(s: str) -> float:
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part)
    return total


def _weight(text: str) -> int:
    return max(1, len(spoken_text(text).split()))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join((text or "").split()))
    return [p.strip() for p in parts if p.strip()]


def _parse_srt(text: str) -> list[ScriptLine]:
    lines: list[ScriptLine] = []
    cur: ScriptLine | None = None
    def secs(h: str | None, mnt: str, sec: str, ms: str | None) -> float:
        return int(h or 0) * 3600 + int(mnt) * 60 + int(sec) + (int(ms.ljust(3, "0")) / 1000 if ms else 0)

    for raw in text.splitlines():
        m = _SRT_CUE.match(raw)
        if m:
            cur = ScriptLine(text="", t_start=secs(*m.groups()[:4]), t_end=secs(*m.groups()[4:8]))
            lines.append(cur)
            continue
        s = raw.strip()
        if not s:
            cur = None  # blank line ends a cue; the next cue's index line is skipped below
            continue
        if cur is None:
            continue  # cue counter ("12") or stray header (WEBVTT) between cues
        cur.text = f"{cur.text} {s}".strip()
    return [ln for ln in lines if ln.text]


def _pack(lines: list[ScriptLine]) -> list[ScriptLine]:
    """Fold fragments into a neighbour: an unpinned line joins the one before it
    when either of them is short ("That's it." carries the sentence after it).
    A pinned line never moves, so a pin is never swallowed; the merged line
    ends where its later part ended."""
    out: list[ScriptLine] = []
    for ln in lines:
        if out and ln.t_start is None and (
            _weight(ln.text) < MIN_LINE_WORDS or _weight(out[-1].text) < MIN_LINE_WORDS
        ):
            prev = out[-1]
            out[-1] = ScriptLine(f"{prev.text} {ln.text}", prev.t_start,
                                 ln.t_end if ln.t_end is not None else prev.t_end)
        else:
            out.append(ScriptLine(ln.text, ln.t_start, ln.t_end))
    return out


def parse_script(text: str) -> list[ScriptLine]:
    """Script text -> ordered lines. SRT cues become one pinned line each.
    Otherwise the text is split into sentences; a leading timestamp pins the
    sentence that follows it. Pins that do not strictly increase are dropped
    (the line stays, unpinned) rather than trusted."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if any(_SRT_CUE.match(raw) for raw in text.splitlines()):
        lines = _parse_srt(text)
    else:
        # A bracketed stamp may sit mid-paragraph ("… invoice. [0:20] Click …"):
        # give each its own line so the leading-stamp rule below sees it. A bare
        # `1:02` only counts at the start of a line — mid-sentence it is prose.
        text = _INLINE_STAMP.sub(r"\n\1", text)
        lines = []
        buf: list[str] = []
        pin: float | None = None
        end: float | None = None

        def flush() -> None:
            nonlocal buf, pin, end
            sents = _sentences(" ".join(buf))
            for i, sent in enumerate(sents):
                # the start pins the chunk's first sentence, the end closes its last
                lines.append(ScriptLine(sent, pin if i == 0 else None,
                                        end if i == len(sents) - 1 else None))
            buf, pin, end = [], None, None

        rows = text.split("\n")
        stamped = any(_STAMP.match(r) for r in rows)
        for raw in rows:
            m = _STAMP.match(raw)
            if m:
                flush()
                g = m.groupdict()
                pin = _clock(next(v for k, v in g.items() if k.startswith("s") and v))
                e = next((v for k, v in g.items() if k.startswith("e") and v), None)
                end = _clock(e) if e else None
                raw = _cell_text(raw[m.end():])
            elif stamped and not buf and _is_header(raw):
                continue  # table header above a timed storyboard
            if raw.strip():
                buf.append(raw.strip())
        flush()
        lines = _pack(lines)

    last = -1.0
    for ln in lines:
        if ln.t_start is not None:
            if ln.t_start <= last:
                ln.t_start = None
            else:
                last = ln.t_start
        if ln.t_end is not None and ln.t_end <= last:
            ln.t_end = None  # an end before the chunk's start means nothing
    return lines


def script_text(lines: list[ScriptLine]) -> str:
    """The narration alone (timestamps and cue numbers gone), in order."""
    return " ".join(ln.text for ln in lines)


# --------------------------------------------------------------------------- #
# Kept-time axis: trim / keep ranges remove footage, so starts are computed on
# the concatenation of the kept spans and mapped back to the source clock.
# --------------------------------------------------------------------------- #
def _norm_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = sorted((max(0.0, float(a)), float(b)) for a, b in spans if b > a)
    return out or [(0.0, 0.0)]


def _total(spans: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in spans)


def to_kept(t: float, spans: list[tuple[float, float]]) -> float:
    """Source time -> kept time; a time inside a removed gap maps to the gap's end."""
    acc = 0.0
    for a, b in spans:
        if t <= a:
            return acc
        if t < b:
            return acc + (t - a)
        acc += b - a
    return acc


def to_source(k: float, spans: list[tuple[float, float]], *, end: bool = False) -> float:
    """Kept time -> source time. Exactly on a span edge, a window START belongs to
    the next span and a window END to the previous one, so no window opens or
    closes inside removed footage."""
    acc = 0.0
    for i, (a, b) in enumerate(spans):
        length = b - a
        last = i == len(spans) - 1
        if k < acc + length or last or (end and k == acc + length):
            return a + min(length, max(0.0, k - acc))
        acc += length
    return spans[-1][1]


def fit_lines(lines: list[ScriptLine], max_n: int) -> list[ScriptLine]:
    """Merge the smallest adjacent pairs until at most `max_n` lines remain (a
    long script over a short clip). Prefers folding an unpinned line into the one
    before it; a pin is only dropped when nothing else is left to merge."""
    lines = [ScriptLine(ln.text, ln.t_start, ln.t_end) for ln in lines]
    max_n = max(1, max_n)
    while len(lines) > max_n:
        pairs = [i for i in range(len(lines) - 1) if lines[i + 1].t_start is None]
        pairs = pairs or list(range(len(lines) - 1))
        i = min(pairs, key=lambda j: _weight(lines[j].text) + _weight(lines[j + 1].text))
        a, b = lines[i], lines[i + 1]
        lines[i : i + 2] = [ScriptLine(f"{a.text} {b.text}", a.t_start,
                                       b.t_end if b.t_end is not None else a.t_end)]
    return lines


def proportional_starts(weights: list[int], pins: list[float | None], total: float) -> list[float]:
    """Start of each line on the kept axis: pins as given, the lines between two
    anchors sharing that span by word count. Line 0 is anchored at 0 when unpinned."""
    n = len(weights)
    starts = [0.0] * n
    anchors = [(i, p) for i, p in enumerate(pins) if p is not None]
    if not anchors or anchors[0][0] != 0:
        anchors.insert(0, (0, 0.0))
    anchors.append((n, total))
    for (i0, k0), (i1, k1) in zip(anchors, anchors[1:]):
        group = sum(weights[i0:i1]) or 1
        acc = 0
        for i in range(i0, i1):
            starts[i] = k0 + (k1 - k0) * acc / group
            acc += weights[i]
    return starts


def valid_starts(starts: Any, n: int, total: float) -> bool:
    """A model's answer is usable only if it is exactly one finite, in-range,
    non-decreasing time per line. Anything else falls back to proportional."""
    if not isinstance(starts, list) or len(starts) != n:
        return False
    prev = 0.0
    for s in starts:
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s):
            return False
        if s < prev or s > total:
            return False
        prev = float(s)
    return True


def snap_starts(
    starts: list[float], pinned: list[bool], cuts: list[float], total: float
) -> list[float]:
    """Move each unpinned start (never the first) onto the nearest scene change
    within tolerance. The tolerance is capped by the neighbouring scenes' length
    so a snap can't swallow a short scene."""
    if not cuts:
        return list(starts)
    out = list(starts)
    for i in range(1, len(starts)):
        if pinned[i]:
            continue
        before = starts[i] - starts[i - 1]
        after = (starts[i + 1] if i + 1 < len(starts) else total) - starts[i]
        tol = min(SNAP_MAX_S, SNAP_SHARE * max(0.0, min(before, after)))
        best = min(cuts, key=lambda c: abs(c - starts[i]))
        if abs(best - starts[i]) <= tol:
            out[i] = best
    return out


def _space(starts: list[float], pinned: list[bool], total: float) -> list[float]:
    """Keep starts in order with MIN_SCENE_S between them where there is room.
    Pins never move; if two pins leave no room, the lines between them collapse
    to a zero-length window (rendered as a held frame) rather than reorder."""
    out = list(starts)
    n = len(out)
    for i in range(1, n):
        if not pinned[i]:
            out[i] = max(out[i], out[i - 1] + MIN_SCENE_S)
    for i in range(n - 1, 0, -1):
        ceiling = (out[i + 1] if i + 1 < n else total) - MIN_SCENE_S
        if not pinned[i] and out[i] > ceiling:
            out[i] = ceiling
    for i in range(1, n):
        if out[i] < out[i - 1]:
            if pinned[i]:
                j = i - 1
                while j > 0 and not pinned[j] and out[j] > out[i]:
                    out[j] = out[i]
                    j -= 1
            else:
                out[i] = out[i - 1]
    return [min(total, max(0.0, s)) for s in out]


def _frame_near(t: float, keyframes: list[tuple[float, str]]) -> str | None:
    if not keyframes:
        return None
    return min(keyframes, key=lambda kf: abs(kf[0] - t))[1]


def script_steps(
    lines: list[ScriptLine],
    spans: list[tuple[float, float]],
    keyframes: list[tuple[float, str]],
    cuts: list[float],
    llm_starts: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Candidate steps (segment()'s shape) — one per script line, windows
    partitioning the kept `spans`. `llm_starts` are source-clock seconds, one per
    line of `lines` as passed in; they are ignored if lines had to be merged."""
    spans = _norm_spans(spans)
    total = _total(spans)
    if not lines:
        return []
    fitted = fit_lines(lines, int(total / MIN_SCENE_S))
    if len(fitted) != len(lines):
        llm_starts = None
    lines = fitted
    n = len(lines)

    # Pins on the kept axis; one that falls outside the kept video, or not after
    # the previous pin once mapped, is dropped.
    pins: list[float | None] = []
    last = -1.0
    for ln in lines:
        k = to_kept(ln.t_start, spans) if ln.t_start is not None else None
        if k is not None and (k <= last or k >= total):
            k = None
        if k is not None:
            last = k
        pins.append(k)
    pinned = [p is not None for p in pins]

    starts = proportional_starts([_weight(ln.text) for ln in lines], pins, total)
    if llm_starts is not None and valid_starts(llm_starts, n, spans[-1][1]):
        for i in range(1, n):
            if not pinned[i]:
                starts[i] = to_kept(float(llm_starts[i]), spans)
    # Span edges count as scene changes: a boundary next to removed footage
    # should sit exactly on the cut the user made.
    edges, acc = [], 0.0
    for a, b in spans[:-1]:
        acc += b - a
        edges.append(acc)
    cuts_k = sorted({round(to_kept(c, spans), 3) for c in cuts if spans[0][0] < c < spans[-1][1]} | set(edges))
    starts = _space(snap_starts(starts, pinned, cuts_k, total), pinned, total)

    steps: list[dict[str, Any]] = []
    if starts[0] > LEAD_IN_S:  # first line pinned late: keep the opening footage, unnarrated
        t0 = to_source(0.0, spans)
        steps.append(_step("Intro", "", t0, to_source(starts[0], spans, end=True), keyframes))
    else:
        starts[0] = 0.0
    for i, ln in enumerate(lines):
        k1 = starts[i + 1] if i + 1 < n else total
        # A user-written end time closes the scene early: the footage from there
        # to the next line is a blank, unnarrated scene (same shape as the
        # "Silence" steps a spoken recording gets), unless the gap is negligible.
        # (It sits on a chunk's last sentence, which may itself be unpinned.)
        k_end = to_kept(ln.t_end, spans) if ln.t_end is not None else None
        blank = k_end is not None and starts[i] < k_end < k1 - GAP_MIN_S
        k_close = k_end if blank else k1
        t0 = to_source(starts[i], spans)
        t1 = max(t0, to_source(k_close, spans, end=True))
        steps.append(_step(spoken_text(ln.text)[:80] or f"Scene {i + 1}", ln.text, t0, t1, keyframes))
        if blank:
            steps.append(_step(BLANK_TARGET, "", t1, max(t1, to_source(k1, spans, end=True)), keyframes))
    return steps


def _step(target: str, narration: str, t0: float, t1: float, keyframes: list[tuple[float, str]]) -> dict[str, Any]:
    return {
        "action": "custom",
        "target": target,
        "selector": None,
        "bbox": None,
        # a beat into the window: the frame AT a boundary is often mid-transition
        "screenshot": _frame_near(t0 + min(1.0, (t1 - t0) / 2), keyframes),
        "t_start": round(t0, 3),
        "t_end": round(t1, 3),
        "narration_span": narration,
    }
