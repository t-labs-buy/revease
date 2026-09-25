"""AI script rewrite via Claude (official Anthropic SDK). Rewrites narration lines
to be clearer and more natural to speak, preserving meaning and product names.
Degrades with a clear error when no key is configured."""

from __future__ import annotations

import json
import re
import logging

from app.llm import complete, has_llm, provider_name
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
    return [str(x).strip() for x in arr]


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
    "- Timing budget: each scene includes its on-screen duration in seconds. Write about "
    "2 to 2.5 words per second for that scene and NEVER more — the video's final length "
    "depends on it. Minimum one short sentence.\n"
    "- Ground truth only: never invent features, results, or UI the scene data does not "
    "mention. Keep every product and feature name exactly as given.\n"
    "- Banned words/phrases: 'simply', 'just', 'easy', 'basically', 'as you can see', "
    "'go ahead', 'now let's'.\n"
    "Return exactly one narration line per scene, in order."
)


def _gen_prompt(scenes: list[dict], title: str, instruction: str | None) -> str:
    extra = f"\nAlso follow this instruction: {instruction}\n" if instruction else ""
    return (
        f'Video title: "{title}". Write the narration script. Respect each scene\'s '
        '"seconds" budget (about 2 to 2.5 words per second, never more). Reply with ONLY a '
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


@observe(name="ai-generate-script")
def generate_script(scenes: list[dict], title: str = "Product demo", instruction: str | None = None) -> list[str]:
    """Write a coherent narration line for each scene (using its target/action + any
    existing note as context)."""
    if not scenes:
        return []
    if not has_llm():
        raise RuntimeError("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY in .env)")

    def work(start: int, batch: list[dict]) -> list[str]:
        return _call_claude(GEN_SYSTEM, _gen_prompt(batch, title, instruction) + _part_note(start, batch, len(scenes)), len(batch))

    results = _run_batches(scenes, work)
    if all(r is None for _, _, r in results):
        raise RuntimeError("the AI did not answer in time — try again")
    lines: list[str] = []
    for _start, batch, res in results:  # a failed batch keeps its current narration
        lines += res if res is not None else [str(sc.get("narration") or "") for sc in batch]
    return lines


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
