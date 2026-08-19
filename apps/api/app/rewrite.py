"""AI script rewrite via Claude (official Anthropic SDK). Rewrites narration lines
to be clearer and more natural to speak, preserving meaning and product names.
Degrades with a clear error when no key is configured."""

from __future__ import annotations

import json
import logging

from app.config import get_settings
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
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("no Anthropic API key configured (set REFRACT_ANTHROPIC_API_KEY in .env)")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    # Adaptive thinking spends from the same max_tokens cap as the visible
    # output, so a budget-scaled cap starves short scripts and truncates the
    # JSON mid-array. max_tokens is a ceiling, not a spend — keep it high.
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "max_tokens":
        raise ValueError("model output was truncated (max_tokens reached) — try again")
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return _parse(text, n)


@observe(name="ai-generate-script")
def generate_script(scenes: list[dict], title: str = "Product demo", instruction: str | None = None) -> list[str]:
    """Write a coherent narration line for each scene (using its target/action + any
    existing note as context)."""
    if not scenes:
        return []
    return _call_claude(GEN_SYSTEM, _gen_prompt(scenes, title, instruction), len(scenes))


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
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("no Anthropic API key configured (set REFRACT_ANTHROPIC_API_KEY in .env)")
    target = target if target in ("video", "doc") else "doc"
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=6000,
        thinking={"type": "adaptive"},
        system=SKILL_SYSTEM,
        messages=[{"role": "user", "content": f"target={target}. Build this skill:\n{prompt}"}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
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
    settings = get_settings()
    if not settings.anthropic_api_key:
        return steps
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
        payload = [{"title": s.get("title", ""), "body": s.get("body", "")} for s in steps]
        prompt = (
            "Restyle each step. " + (instruction or "") + " Reply with ONLY a JSON array of "
            'objects {"title","body"}, exactly one per input step, in the same order.\n\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=DOC_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
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


TITLE_SYSTEM = (
    "You write a short, specific title for a screen-recording / product-demo video, "
    "based on its narration transcript. 3 to 6 words, Title Case, no surrounding quotes, "
    "no trailing punctuation. Reply with ONLY the title."
)


@observe(name="ai-title")
def generate_title(text: str) -> str:
    """Concise title from a transcript. Returns "" when there's nothing to title
    (caller keeps the existing name). Falls back to a heuristic without a key."""
    text = (text or "").strip()
    if not text:
        return ""
    settings = get_settings()
    if not settings.anthropic_api_key:
        words = text.split()[:6]
        return " ".join(words).strip(" .,-").title()[:80]
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60)
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=TITLE_SYSTEM,
            messages=[{"role": "user", "content": text[:4000]}],
        )
        out = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return out.strip().strip('"').strip().rstrip(".")[:80]
    except Exception as e:  # pragma: no cover - env dependent
        log.warning("title generation failed (%s); using heuristic.", e)
        return " ".join(text.split()[:6]).strip(" .,-").title()[:80]


ZOOM_SYSTEM = (
    "You are a video editor deciding where a zoom-in adds emphasis in a product demo. "
    "For each scene (with its narration and UI target/action) decide whether zooming in "
    "helps the viewer focus on a specific element or action. Zoom in when the scene "
    "references a specific button, field, menu, or a click/type action, or when the "
    "narration draws attention ('notice', 'here', 'click', 'select'). Do NOT zoom on "
    "intro, overview, summary, or transition scenes. Scale higher for smaller targets."
)


@observe(name="ai-suggest-zooms")
def suggest_zooms(scenes: list[dict]) -> list[dict]:
    """Return a {zoom, scale} suggestion per scene."""
    if not scenes:
        return []
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("no Anthropic API key configured (set REFRACT_ANTHROPIC_API_KEY in .env)")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    prompt = (
        "Decide the zoom for each scene. Reply with ONLY a JSON array (no prose, no code "
        'fences) — one object per scene, same order: {"zoom": true|false, "scale": number '
        "between 1.3 and 2.0}.\n\nScenes:\n" + json.dumps(scenes, ensure_ascii=False)
    )
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=ZOOM_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    arr = json.loads(t)
    if not isinstance(arr, list) or len(arr) != len(scenes):
        raise ValueError(f"expected {len(scenes)} zoom suggestions, got {len(arr) if isinstance(arr, list) else '?'}")
    return [
        {"zoom": bool(x.get("zoom")), "scale": max(1.0, min(2.5, float(x.get("scale", 1.5))))}
        for x in arr
    ]


@observe(name="ai-rewrite")
def rewrite_lines(lines: list[str], instruction: str | None = None) -> list[str]:
    """Return a rewritten version of each line (same length/order). Empty lines pass
    through untouched; an empty rewrite falls back to the original."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("no Anthropic API key configured (set REFRACT_ANTHROPIC_API_KEY in .env)")
    clean = [ln.strip() for ln in lines]
    if not any(clean):
        return list(lines)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    # thinking tokens count against max_tokens — don't scale the cap to input size
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(clean, instruction)}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    out = _parse(text, len(clean))
    # keep the original where the model returned an empty string
    return [o or lines[i] for i, o in enumerate(out)]
