"""AI script rewrite via Claude (official Anthropic SDK). Rewrites narration lines
to be clearer and more natural to speak, preserving meaning and product names.
Degrades with a clear error when no key is configured."""

from __future__ import annotations

import json
import re
import logging

from app.llm import complete, complete_vision, has_llm, provider_name
from app.tracing import observe

log = logging.getLogger("refract.rewrite")

SYSTEM = (
    "You are a technical scriptwriter polishing narration lines that a TTS voice speaks "
    "over a screen recording of a software product (often technical/enterprise software).\n\n"
    "Rewrite each line for clarity and correctness:\n"
    "- Clear, precise, natural to speak aloud. Present tense, active voice.\n"
    "- Preserve EVERY technical detail: system names, field names, protocol names, file "
    "types, button/menu labels, numbers, and step order — never summarize, generalize, or "
    "drop specifics to save space.\n"
    "- Fix grammar, remove true filler ('um', 'basically', 'so yeah'), and smooth awkward "
    "phrasing — but do not shorten a line just to make it punchier.\n"
    "- TTS-safe: plain spoken words only — no emojis, markdown, parentheses, or stage "
    "directions; expand awkward abbreviations; keep numbers easy to say.\n"
    "- Preserve the exact meaning and every product, feature, and proper name exactly as "
    "written.\n"
    "- Each rewrite should stay close to its original length — moderately longer is fine "
    "if needed for technical accuracy, but avoid runaway expansion (the video's timing "
    "still depends on it).\n"
    "- Never split one input line into multiple output lines, even if it becomes long or "
    "covers several actions — one input line always produces exactly one output string, no "
    "matter how much detail it needs to carry. If a line covers multiple steps, write one "
    "longer sentence connecting them, not two separate lines.\n"
    "Return exactly one rewrite per input line, in the same order — never merge, split, "
    "add, or drop lines."
)



def _prompt(lines: list[str], instruction: str | None) -> str:
    extra = f"\nAlso follow this instruction: {instruction}\n" if instruction else ""
    return (
        "Rewrite each of these narration lines. Reply with ONLY a JSON array of strings "
        "(no prose, no code fences) — exactly one rewritten string per input line, same "
        "order." + extra + "\n\n" + json.dumps(lines, ensure_ascii=False)
    )


def _parse(text: str, n: int) -> list[str]:
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    arr = json.loads(t)
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError(f"expected {n} lines, got {type(arr).__name__} of {len(arr) if isinstance(arr, list) else '?'}")
    return [_line_of(x) for x in arr]


def _line_of(item: object) -> str:
    """A model sometimes answers in the shape it was asked in — `{"line": …,
    "max_words": 23}` instead of the bare string — and str() of that object
    once became a scene's narration. Unwrap it; anything else is text."""
    if isinstance(item, dict):
        for key in ("line", "text", "narration"):
            if isinstance(item.get(key), str):
                return item[key].strip()
    return str(item).strip()


GEN_SYSTEM = (
    "You are a senior product-marketing scriptwriter creating the voiceover for a "
    "professional SaaS product-demo video. The script is spoken by a TTS voice over a "
    "screen recording — one line per scene, in scene order.\n\n"
    "Write a production-ready walkthrough:\n"
    "- Scene 1 is the hook: name the product or workflow and the outcome the viewer gets, "
    "in one tight sentence. Never open with 'In this video we will'.\n"
    "- Each middle scene narrates what is happening on screen (its action/target) and why "
    "it matters — action first, benefit second.\n"
    "- The final scene closes in one sentence with the result achieved — a natural wrap, "
    "not a sales pitch.\n"
    "- Voice: confident, warm, professional. Speak to the viewer as 'you'. Present tense, "
    "active voice. Vary sentence openers so scenes flow as one continuous demo, never a "
    "list of captions.\n"
    "- TTS-safe: plain spoken words only — no emojis, markdown, parentheses, stage "
    "directions, or camera notes. Expand awkward abbreviations; keep numbers easy to say.\n"
    "- Timing budget: each scene carries \"max_words\", the most words its footage can "
    "carry before the picture would freeze waiting for the voice. Count your words; never "
    "exceed it. Prefer one tight sentence; split nothing across scenes. A scene with "
    "max_words 0 gets an empty string — the footage simply plays.\n"
    "- Ground truth only: never invent features, results, or UI the scene data does not "
    "mention. Keep every product and feature name exactly as given.\n"
    "- Banned words/phrases: 'simply', 'just', 'easy', 'basically', 'as you can see', "
    "'go ahead', 'now let's'.\n"
    "Return exactly one narration line per scene, in order."
)


def _gen_prompt(scenes: list[dict], title: str, instruction: str | None) -> str:
    extra = f"\nAlso follow this instruction: {instruction}\n" if instruction else ""
    return (
        f'Video title: "{title}". Write the narration script. Each scene\'s "max_words" is a '
        "hard limit — count the words of every line. Reply with ONLY a "
        "JSON array of strings (no prose, no code fences) — exactly one narration line per "
        "scene, same order."
        + extra
        + "\n\nScenes:\n"
        + json.dumps(scenes, ensure_ascii=False)
    )


def _call_claude(system: str, prompt: str, n: int) -> list[str]:
    if not has_llm():
        raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY in .env)")
    return _parse(complete(system, prompt, max_tokens=16000, timeout=AI_DEADLINE_S), n)


# These AI calls answer an HTTP request directly, and the public path goes
# through nginx-proxy-manager, whose default read timeout is 60s. One call over
# a 162-scene project took well over a minute (and the browser got a 504), so
# large inputs are split into batches that run in parallel under a deadline.
AI_DEADLINE_S = 45
BATCH = 30


def _run_batches(items: list, work, *, size: int = BATCH, deadline_s: float | None = None):
    """[(start, batch, result|None)] — result is None when that batch failed or
    missed the deadline, so callers fall back for just those items."""
    from concurrent.futures import ThreadPoolExecutor, wait

    deadline_s = AI_DEADLINE_S if deadline_s is None else deadline_s
    batches = [(i, items[i:i + size]) for i in range(0, len(items), size)]
    pool = ThreadPoolExecutor(max_workers=min(8, len(batches)) or 1)
    futures = [pool.submit(work, start, batch) for start, batch in batches]
    done, _late = wait(futures, timeout=deadline_s)
    out = []
    for (start, batch), fut in zip(batches, futures):
        if fut in done and fut.exception() is None:
            out.append((start, batch, fut.result()))
        else:
            reason = fut.exception() if fut in done else f"no answer within {deadline_s:.0f}s"
            log.warning("AI batch %d-%d failed: %s", start, start + len(batch) - 1, reason)
            out.append((start, batch, None))
    pool.shutdown(wait=False, cancel_futures=True)  # late calls finish in the background, ignored
    return out


def _part_note(start: int, batch: list, total: int) -> str:
    if len(batch) == total:
        return ""
    return f"\n(These are scenes {start + 1}-{start + len(batch)} of {total}; keep the style consistent.)\n"


GEN_FRAMES_NOTE = (
    "\n\nEach scene below is followed by a frame from the recording at that scene. Narrate "
    "what the frame shows — name the pages, buttons and fields you can actually read — and "
    "never describe UI that is not visible. A scene's \"target\" may be a generic placeholder "
    "(\"Screen 3\") when the recording had no clicks or speech; trust the frame over it."
)
# Frames are heavy: fewer scenes per call keeps each call inside AI_DEADLINE_S.
FRAMES_BATCH = 12


def _gen_with_frames(batch: list[dict], prompt: str) -> str:
    """One Generate call that also shows the model each scene's frame — the
    only way to narrate a recording that had no clicks and no speech. Scenes
    whose frame can't be loaded are simply described in text."""
    from app.frames import frame_jpeg

    parts: list[str | bytes] = [prompt]
    for i, sc in enumerate(batch):
        img = frame_jpeg(sc.get("screenshot"))
        if img is not None:
            parts += [f"Frame for scene {i + 1}:", img]
    return complete_vision(GEN_SYSTEM + GEN_FRAMES_NOTE, parts, max_tokens=16000, timeout=AI_DEADLINE_S)


# A generated line must fit its footage: the render retimes a scene to its TTS
# length + SCENE_GAP_MS and FREEZES the last frame when the voice runs past
# the window (render.py). Kokoro speaks ~2.6 words/s at speed 1 (tts.py); the
# budget uses a little less so a long word or a comma does not tip a scene over.
BUDGET_WORDS_PER_S = 2.3
SCENE_GAP_S = 0.8


def scene_word_budget(seconds: float, speed: float = 1.0) -> int:
    """Most words a scene of `seconds` can carry at voice `speed` (speed × pace)
    without the picture freezing. 0 for a scene too short to say anything."""
    return max(0, int((float(seconds or 0) - SCENE_GAP_S) * BUDGET_WORDS_PER_S * max(0.5, speed)))


def _word_count(line: str) -> int:
    return len(line.split())


def fit_to_budget(line: str, max_words: int) -> str:
    """Last resort after the model ignored its budget twice: drop trailing
    sentences until the line fits. A single sentence that is still over stays
    whole — a cut-off sentence read aloud is worse than a short freeze."""
    if _word_count(line) <= max_words:
        return line
    if max_words <= 0:
        return ""
    sents = re.split(r"(?<=[.!?])\s+", line.strip())
    while len(sents) > 1 and _word_count(" ".join(sents)) > max_words:
        sents.pop()
    return " ".join(sents).strip()


SHORTEN_SYSTEM = (
    "You tighten narration lines for a TTS voiceover so each fits a hard word limit. "
    "Keep the meaning, the product names and the tone; cut filler and secondary clauses. "
    "Count the words. Reply with ONLY a JSON array of the shortened lines as plain strings, "
    "one per line, same order — no objects, no keys, no word counts."
)


def _shorten(lines: list[str], limits: list[int]) -> list[str]:
    # lines and limits as two flat lists: there is no object shape to echo back
    prompt = (
        "Lines:\n" + json.dumps(lines, ensure_ascii=False)
        + "\nWord limit for each line, same order:\n" + json.dumps(limits)
        + "\nShorten each line to at most its limit."
    )
    return _call_claude(SHORTEN_SYSTEM, prompt, len(lines))


def enforce_budgets(lines: list[str], limits: list[int | None]) -> list[str]:
    """Lines that overran their scene go back once to be shortened, then are
    trimmed at a sentence boundary. Budget-less scenes (limit None) pass through."""
    over: list[tuple[int, int]] = [
        (i, m) for i, (ln, m) in enumerate(zip(lines, limits)) if m is not None and _word_count(ln) > m
    ]
    if not over:
        return lines
    out = list(lines)
    try:
        shorter = _shorten([lines[i] for i, _ in over], [m for _, m in over])
        for (i, _), ln in zip(over, shorter):
            out[i] = ln
    except Exception as e:
        log.warning("shorten pass failed (%s); trimming at sentence boundaries", e)
    for i, m in over:
        out[i] = fit_to_budget(out[i], m)
    return out


@observe(name="ai-generate-script")
def generate_script(scenes: list[dict], title: str = "Product demo", instruction: str | None = None) -> list[str]:
    """Write a coherent narration line for each scene (using its target/action + any
    existing note as context, and its frame when the editor sends `screenshot`),
    each no longer than its footage can carry (`max_words`, or derived from
    `seconds`). Runs only when the user presses Generate — the pipeline never
    calls this."""
    if not scenes:
        return []
    if not has_llm():
        raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY in .env)")
    with_frames = any(sc.get("screenshot") for sc in scenes)
    limits: list[int | None] = [
        int(sc["max_words"]) if sc.get("max_words") is not None
        else scene_word_budget(sc["seconds"]) if sc.get("seconds") is not None
        else None
        for sc in scenes
    ]
    text_only = [
        {**{k: v for k, v in sc.items() if k not in ("screenshot", "seconds")}, "max_words": m}
        if m is not None else {k: v for k, v in sc.items() if k != "screenshot"}
        for sc, m in zip(scenes, limits)
    ]

    def work(start: int, batch: list[dict]) -> list[str]:
        prompt = _gen_prompt(text_only[start:start + len(batch)], title, instruction) + _part_note(start, batch, len(scenes))
        if with_frames:
            return _parse(_gen_with_frames(batch, prompt), len(batch))
        return _call_claude(GEN_SYSTEM, prompt, len(batch))

    results = _run_batches(scenes, work, size=FRAMES_BATCH if with_frames else BATCH)
    if all(r is None for _, _, r in results):
        raise RuntimeError("the AI did not answer in time — try again")
    lines: list[str] = []
    generated: list[bool] = []
    for _start, batch, res in results:  # a failed batch keeps its current narration
        lines += res if res is not None else [str(sc.get("narration") or "") for sc in batch]
        generated += [res is not None] * len(batch)
    # only what the model wrote is held to the budget; kept narration is the user's
    return enforce_budgets(lines, [m if g else None for m, g in zip(limits, generated)])


SKILL_SYSTEM = (
    "You design a reusable AI-generation 'skill' (template) for a screen-recording product. "
    "You may ONLY use the capabilities the tool actually supports — never invent fields, "
    "sections it can't render, or settings not listed. Return a single JSON object, no prose, "
    "no code fences.\n\n"
    "Schema (use exactly these keys):\n"
    "{\n"
    '  "name": string,\n'
    '  "description": string (one line),\n'
    '  "target": "video" | "doc",\n'
    '  "tags": string[] (2-5 short tags),\n'
    '  "overall_instructions": string (global guidance for the AI),\n'
    "  // for target=doc only:\n"
    '  "sections": [ { "title": string, "description": string (the AI prompt for that section), "include_screenshots": boolean } ],\n'
    '  "formatting": { "fonts": { "heading1": {"family": string, "color": "#RRGGBB", "size": number}, "heading2": {...}, "heading3": {...}, "paragraph": {...} }, "logo_position": "Top Left"|"Top Center"|"Top Right"|"Bottom Left"|"Bottom Right", "block_quote": {"color":"#RRGGBB","family": string} },\n'
    "  // for target=video only:\n"
    '  "voice_id": one of ["af_sarah","af_bella","af_heart","am_adam","am_michael","bf_emma","bm_george"],\n'
    '  "speed": number 0.75..1.5, "captions": boolean, "motion_zoom": boolean,\n'
    '  "instruction": string (how to rewrite the narration)\n'
    "}\n"
    "font family must be one of: Geist, Inter, Arial, Georgia. Keep it realistic and useful."
)


@observe(name="ai-skill-builder")
def generate_skill(prompt: str, target: str = "doc") -> dict:
    """Design a skill from a natural-language description, constrained to tool
    capabilities. Returns {name, description, target, settings}."""
    if not has_llm():
        raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY in .env)")
    target = target if target in ("video", "doc") else "doc"
    text = complete(SKILL_SYSTEM, f"target={target}. Build this skill:\n{prompt}", max_tokens=6000)
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    obj = json.loads(t)
    if not isinstance(obj, list):
        pass
    tgt = obj.get("target") if obj.get("target") in ("video", "doc") else target
    # everything except the top-level fields becomes the skill's settings blob
    top = {"name", "description", "target"}
    return {
        "name": str(obj.get("name") or "New Skill")[:120],
        "description": str(obj.get("description") or "")[:400],
        "target": tgt,
        "settings": {k: v for k, v in obj.items() if k not in top},
    }


DOC_SYSTEM = (
    "You restyle the steps of a how-to document. For each step you receive a title and "
    "body. Rewrite both in the requested style, preserving the meaning and any product or "
    "feature names exactly. Return exactly one object per input step, in the same order."
)


@observe(name="ai-doc-style")
def restyle_doc(steps: list[dict], instruction: str) -> list[dict]:
    """Rewrite each doc step's title/body in a requested style (SOP / Quick / FAQ).
    Returns the steps unchanged when there's no key or on any failure."""
    if not steps:
        return steps
    if not has_llm():
        return steps
    try:
        payload = [{"title": s.get("title", ""), "body": s.get("body", "")} for s in steps]
        prompt = (
            "Restyle each step. " + (instruction or "") + " Reply with ONLY a JSON array of "
            'objects {"title","body"}, exactly one per input step, in the same order.\n\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        text = complete(DOC_SYSTEM, prompt, max_tokens=16000)
        t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        arr = json.loads(t)
        if not isinstance(arr, list) or len(arr) != len(steps):
            return steps
        out = []
        for s, r in zip(steps, arr):
            out.append(
                {
                    **s,
                    "title": (str(r.get("title") or s.get("title", ""))[:160]),
                    "body": (str(r.get("body") or s.get("body", ""))),
                }
            )
        return out
    except Exception as e:  # pragma: no cover
        log.warning("doc restyle failed (%s); keeping original.", e)
        return steps




@observe(name="ai-title")
def generate_title(text: str, steps: list[dict] | None = None) -> str:
    """Concise project title from a recording (see app.titles): an LLM given the
    transcript + steps when a key is configured, else an offline heuristic that
    finds the stated goal or dominant topic. "" means keep the current name."""
    from app.titles import project_title

    return project_title(text, steps)


ZOOM_SYSTEM = (
    "You are a video editor deciding where a zoom-in adds emphasis in a product demo. "
    "For each scene (with its narration and UI target/action) decide whether zooming in "
    "helps the viewer focus on a specific element or action. Zoom in when the scene "
    "references a specific button, field, menu, or a click/type action, or when the "
    "narration draws attention ('notice', 'here', 'click', 'select'). Do NOT zoom on "
    "intro, overview, summary, or transition scenes. Scale higher for smaller targets."
)


_ZOOM_CUE = re.compile(r"\b(click|select|choose|type|enter|press|notice|here|this button|this field|tap)\b", re.I)
_ZOOM_SKIP = re.compile(r"\b(intro|introduction|overview|summary|welcome|recap|thank)", re.I)


def heuristic_zooms(scenes: list[dict]) -> list[dict]:
    """The same rules the AI prompt states, applied mechanically: zoom where the
    scene acts on a specific element (a click/type on a named target) or the
    narration points at one; never on intro/overview/summary scenes."""
    out = []
    for sc in scenes:
        action = (sc.get("action") or "").lower()
        target = (sc.get("target") or "").strip()
        narration = sc.get("narration") or ""
        specific = bool(target) and not target.lower().startswith(("silence", "the element", "screen"))
        if _ZOOM_SKIP.search(f"{target} {narration}"):
            out.append({"zoom": False, "scale": 1.0})
        elif specific and action in ("click", "input", "keydown"):
            # short targets are small on screen (a button), long ones are regions
            out.append({"zoom": True, "scale": 1.8 if len(target) <= 18 else 1.5})
        elif _ZOOM_CUE.search(narration):
            out.append({"zoom": True, "scale": 1.5})
        else:
            out.append({"zoom": False, "scale": 1.0})
    return out


def _parse_zoom_picks(text: str, n: int) -> dict[int, float]:
    """{local index: scale} from a reply listing only the scenes to zoom."""
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    i, j = t.find("["), t.rfind("]")
    arr = json.loads(t[i:j + 1] if i >= 0 and j > i else t)
    if not isinstance(arr, list):
        raise ValueError("zoom reply is not a list")
    picks: dict[int, float] = {}
    for x in arr:
        if isinstance(x, dict) and isinstance(x.get("i"), int) and 0 <= x["i"] < n:
            picks[x["i"]] = max(1.2, min(2.5, float(x.get("scale", 1.5))))
    return picks


def _zoom_prompt(batch: list[dict]) -> str:
    listed = [{"i": k, **{f: sc.get(f, "") for f in ("target", "action", "narration")}} for k, sc in enumerate(batch)]
    return (
        "Decide which scenes deserve a zoom-in. Reply with ONLY a JSON array (no prose, no "
        'code fences) listing just those scenes: [{"i": <scene index>, "scale": <1.3 to 2.0>}] '
        "— an empty array [] when none should zoom.\n\nScenes:\n" + json.dumps(listed, ensure_ascii=False)
    )


@observe(name="ai-suggest-zooms")
def suggest_zooms_with_source(scenes: list[dict]) -> tuple[list[dict], str]:
    """(suggestions, source). The AI picks zooms in parallel batches under a
    deadline; any batch it misses (no key, error, too slow) gets the rule-based
    answer for just those scenes, so the button never dead-ends or times out.
    source: the provider, "mixed", or "rules"."""
    if not scenes:
        return [], "none"
    rules = heuristic_zooms(scenes)
    if not has_llm():
        return rules, "rules"

    def work(_start: int, batch: list[dict]) -> dict[int, float]:
        return _parse_zoom_picks(complete(ZOOM_SYSTEM, _zoom_prompt(batch), max_tokens=6000, timeout=AI_DEADLINE_S), len(batch))

    results = _run_batches(scenes, work, size=40)
    out = list(rules)
    answered = 0
    for start, batch, picks in results:
        if picks is None:
            continue
        answered += 1
        for k in range(len(batch)):
            out[start + k] = {"zoom": k in picks, "scale": picks.get(k, 1.0)}
    if answered == 0:
        return rules, "rules"
    return out, provider_name() if answered == len(results) else "mixed"


def suggest_zooms(scenes: list[dict]) -> list[dict]:
    """Return a {zoom, scale} suggestion per scene."""
    return suggest_zooms_with_source(scenes)[0]


@observe(name="ai-rewrite")
def rewrite_lines(lines: list[str], instruction: str | None = None) -> list[str]:
    """Return a rewritten version of each line (same length/order). Empty lines pass
    through untouched; an empty rewrite falls back to the original."""
    if not has_llm():
        raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY in .env)")
    clean = [ln.strip() for ln in lines]
    if not any(clean):
        return list(lines)

    def work(start: int, batch: list[str]) -> list[str]:
        # thinking tokens count against max_tokens — don't scale the cap to input size
        text = complete(SYSTEM, _prompt(batch, instruction), max_tokens=16000, timeout=AI_DEADLINE_S)
        return _parse(text, len(batch))

    results = _run_batches(clean, work)
    if all(r is None for _, _, r in results):
        raise RuntimeError("the AI did not answer in time — try again")
    out: list[str] = []
    for start, batch, res in results:  # a failed batch keeps the original lines
        out += res if res is not None else list(lines[start:start + len(batch)])
    # keep the original where the model returned an empty string
    return [o or lines[i] for i, o in enumerate(out)]
