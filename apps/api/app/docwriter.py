"""Documentation writer — turns a Workflow Graph + transcript into a DocV2 (see
schemas.py), without snapshots (the worker attaches those).

Why it lives in the API package: the worker imports the API (never the reverse),
and generation runs in the worker because snapshots need ffmpeg — so the prompt
and the deterministic fallback sit here where both sides can reach them.

Why ids, not order: the model returns one entry per graph step *id*; order and
identity always come from the graph (`merge_model_output`), so a model that
reorders, drops or invents steps can never desynchronise text from snapshots.

Why the fallback is computed first: it is the safety net for every failure mode
(no key, timeout, truncated JSON, bad ids) and it is deterministic, which is what
lets the whole test-suite run offline.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.editspec import detect_filler, effective_script, tokenize
from app.schemas import DocV2, clean_text
from app.tracing import observe

log = logging.getLogger("refract.docwriter")

SILENCE_TARGET = "Silence"  # segment.py inserts "Silence — add narration" filler steps

# Transcript budget: per-step narration already carries the middle of the
# recording verbatim, so when the full transcript is too long we keep the head
# (feeds the overview) and the tail (feeds the closing tips).
MAX_TRANSCRIPT_CHARS = 24_000
_HEAD_CHARS = 16_000
_TAIL_CHARS = 8_000
MAX_STEP_NARRATION_CHARS = 1_200

_VERB = {
    "click": "Click",
    "input": "Type into",
    "navigation": "Go to",
    "scroll": "Scroll",
    "keydown": "Press",
    "wait": "Wait for",
    "custom": "Interact with",
}

WRITER_SYSTEM = """You are a senior technical writer producing end-user documentation from a screen recording of a software workflow. You receive (1) the ordered list of recorded steps — each with an id, action, UI target, screen name, an intent label, the time range, and the narration the presenter spoke during that step — and (2) the full transcript. Write a clear, complete how-to guide.

GROUNDING — non-negotiable:
- Only mention UI elements (buttons, menus, fields, pages, labels, values) that appear in the step data or the transcript. Never invent names, fields, options, outcomes, or error messages. If a detail is unclear, describe the action generically ("Fill in the required fields") rather than guessing.
- Product, feature and screen names are copied exactly as given (case, spelling).
- The transcript is speech-to-text and may contain recognition errors and filler; the step data is authoritative when they disagree.

STRUCTURE — every step id marked REQUIRED must appear exactly once, in the given order, with its exact id. Never renumber, reorder, split or invent ids. Steps marked OPTIONAL are silent pauses: either omit them or, when the pause obviously belongs with the surrounding action (a page loading, a result appearing), fold what happened into the neighbouring step's text. Do not output an OPTIONAL step whose only content would be "wait".

WRITING:
- Step title: 3-8 words, imperative, names the action and target ("Open the API Keys page").
- Step body: 1-3 sentences, imperative mood, second person, present tense. Bold UI labels with **double asterisks** ("Click **Save**"). Put literal values the user types in `backticks`. State the visible result when the narration or the next step makes it clear ("The key appears in the list").
- Step tip: optional (null when nothing to add). One sentence for a shortcut, a caveat, or what to do if the expected screen does not appear — only when the transcript supports it.
- Overview: 2-4 sentences: what the guide achieves, who it is for, and the end state. Never start with "In this guide" or "This document".
- Prerequisites: only items the transcript or steps actually evidence (an account, a role, a prior configuration). Empty list when nothing is evidenced.
- Tips: 0-5 closing items: troubleshooting, next steps, gotchas — again only when grounded. Empty list otherwise.
- Banned: "simply", "just", "easy", "as you can see", "go ahead", "now let's", marketing tone, emojis, first person.
- Language: write in the language requested in the user message (default: the language of the transcript).

OUTPUT — reply with ONLY one JSON object (no prose, no code fences), exactly:
{
  "title": string,
  "overview": string,
  "prerequisites": string[],
  "steps": [ { "id": string, "title": string, "body": string, "tip": string | null } ],
  "tips": string[]
}"""


# ---------------------------------------------------------------- helpers ----


def is_silent(step: dict[str, Any]) -> bool:
    """A step with nothing to say and nothing clicked: the segment.py silence
    filler, or any custom step with empty narration and no bbox."""
    target = (step.get("target") or "").strip()
    narration = (step.get("narration") or "").strip()
    if narration:
        return False
    if target.startswith(SILENCE_TARGET):
        return True
    return step.get("action") == "custom" and not step.get("bbox")


def _sentence_case(s: str) -> str:
    s = (s or "").strip().rstrip(".")
    return (s[:1].upper() + s[1:]) if s else s


def _clean_narration(text: str) -> str:
    """Struck fillers, capitalised, terminal punctuation — the same cleanup the
    video editor applies by default, so the doc and the voiceover agree."""
    words = tokenize(text)
    kept = effective_script(words, detect_filler(words))
    kept = _sentence_case(kept)
    if kept and kept[-1] not in ".!?":
        kept += "."
    return kept


def _first_sentences(text: str, n: int = 3, limit: int = 400) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    out = " ".join(p for p in parts[:n] if p).strip()
    return out[:limit]


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def effective_narrations(graph_json: dict[str, Any], edit_spec: dict[str, Any] | None) -> dict[str, str]:
    """step_id -> the narration the user actually kept. Uses the video editor's
    words/removed when an edit spec is given (so script edits reach the doc),
    else the graph narration with fillers struck."""
    out: dict[str, str] = {}
    for s in graph_json.get("steps", []):
        out[s["id"]] = _clean_narration(s.get("narration") or "")
    for seg in (edit_spec or {}).get("segments", []) or []:
        sid = seg.get("step_id")
        if sid in out and isinstance(seg.get("words"), list):
            text = effective_script(seg["words"], seg.get("removed") or [])
            out[sid] = _clean_narration(text) if text else out[sid]
    return out


def _mechanical_step(s: dict[str, Any]) -> dict[str, Any]:
    intent = (s.get("intent") or "").strip()
    if intent:
        title = _sentence_case(intent)
    else:
        verb = _VERB.get(s.get("action") or "custom", "Interact with")
        title = _sentence_case(f"{verb} {s.get('target') or 'the highlighted element'}")
    body = _clean_narration(s.get("narration") or "") or f"{title}."
    return {
        "id": s["id"],
        "title": title[:200],
        "body": body,
        "tip": None,
        "snapshot": None,
        "source": {
            "graph_step_id": s["id"],
            "t_start": s.get("t_start"),
            "t_end": s.get("t_end"),
        },
    }


def _split_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    """(steps to document, ids that are REQUIRED). Silent steps are optional —
    unless every step is silent, in which case all are required so the doc is
    never empty (uploads with no audio and no clicks)."""
    required = {s["id"] for s in steps if not is_silent(s)}
    if not required:
        required = {s["id"] for s in steps}
    return steps, required


# --------------------------------------------------------------- fallback ----


def write_document_fallback(
    *,
    project_title: str,
    transcript_text: str,
    steps: list[dict[str, Any]],
    instruction: str | None = None,
    skill_settings: dict[str, Any] | None = None,
    graph_version: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic, keyless DocV2 (no snapshots)."""
    _, required = _split_steps(steps)
    kept = [s for s in steps if s["id"] in required]
    title = (project_title or "").strip() or "Workflow"
    overview = _first_sentences(transcript_text) or (
        f"This guide walks through the {len(kept)} step{'' if len(kept) == 1 else 's'} "
        f"recorded for “{title}”."
    )
    doc = {
        "version": 2,
        "title": title,
        "overview": overview,
        "prerequisites": [],
        "steps": [_mechanical_step(s) for s in kept],
        "tips": [],
        "meta": {
            "generated_at": _now_iso(now),
            "writer": "fallback",
            "model": None,
            "instruction": instruction,
            "skill_id": None,
            "graph_version": graph_version,
            "snapshots": _skill_wants_snapshots(skill_settings),
        },
    }
    return DocV2.model_validate(doc).model_dump()


# ----------------------------------------------------------------- prompt ----

_SECTION_BUCKETS = [
    ("overview", re.compile(r"overview|intro|summary|purpose|about")),
    ("prerequisites", re.compile(r"prereq|requirement|before you")),
    ("steps", re.compile(r"step|procedure|instruction|how")),
    ("tips", re.compile(r"tip|troubleshoot|faq|next|note|gotcha")),
]


def _bucket(title: str) -> str:
    t = (title or "").lower()
    for name, rx in _SECTION_BUCKETS:
        if rx.search(t):
            return name
    return "other"


def _skill_wants_snapshots(settings: dict[str, Any] | None) -> bool:
    """A doc skill's steps section may switch screenshots off."""
    for sec in (settings or {}).get("sections") or []:
        if isinstance(sec, dict) and _bucket(sec.get("title", "")) == "steps":
            return sec.get("include_screenshots", True) is not False
    return True


def _skill_guidance(settings: dict[str, Any] | None) -> str:
    if not settings:
        return ""
    lines: list[str] = []
    overall = (settings.get("overall_instructions") or "").strip()
    if overall:
        lines.append(f"Overall: {overall}")
    other: list[str] = []
    labels = {
        "overview": "Overview section guidance",
        "prerequisites": "Prerequisites guidance",
        "steps": "Steps guidance",
        "tips": "Closing tips guidance",
    }
    for sec in settings.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        desc = (sec.get("description") or "").strip()
        if not desc:
            continue
        b = _bucket(sec.get("title", ""))
        if b == "other":
            other.append(f"{sec.get('title', 'Section')}: {desc}")
        else:
            lines.append(f"{labels[b]}: {desc}")
    if other:
        lines.append("Other guidance: " + " | ".join(other))
    if not lines:
        return ""
    return "STYLE GUIDE (from the selected skill):\n" + "\n".join(lines) + "\n\n"


def _budget_transcript(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    omitted = len(text) - _HEAD_CHARS - _TAIL_CHARS
    return (
        text[:_HEAD_CHARS]
        + f"\n[… {omitted} characters omitted; every step's own narration is listed above …]\n"
        + text[-_TAIL_CHARS:]
    )


def _fmt_t(v: Any) -> str:
    try:
        return f"{float(v):.1f}s"
    except (TypeError, ValueError):
        return "?"


def _writer_prompt(
    *,
    project_title: str,
    transcript_text: str,
    steps: list[dict[str, Any]],
    required: set[str],
    skill_settings: dict[str, Any] | None,
    instruction: str | None,
    language: str | None,
) -> str:
    n_req = len(required)
    parts = [
        f"Project: {json.dumps(project_title or 'Workflow', ensure_ascii=False)}",
        f"Language: {language or 'the language of the transcript'}",
        f"Graph steps: {len(steps)} total, {n_req} REQUIRED, {len(steps) - n_req} OPTIONAL",
        "",
    ]
    if instruction:
        parts += ["ADDITIONAL INSTRUCTION FROM THE USER:", instruction.strip(), ""]
    guidance = _skill_guidance(skill_settings)
    if guidance:
        parts.append(guidance.rstrip())
        parts.append("")
    parts.append("STEPS:")
    for i, s in enumerate(steps, start=1):
        flag = "REQUIRED" if s["id"] in required else "OPTIONAL (silent pause)"
        head = (
            f"{i}. id={s['id']} {flag}  {_fmt_t(s.get('t_start'))}–{_fmt_t(s.get('t_end'))}  "
            f"action={s.get('action') or 'custom'}  screen={json.dumps(s.get('screen_name') or '', ensure_ascii=False)}  "
            f"target={json.dumps(s.get('target') or '', ensure_ascii=False)}"
        )
        parts.append(head)
        if s.get("intent"):
            parts.append(f"   intent: {s['intent']}")
        narration = (s.get("narration") or "").strip()[:MAX_STEP_NARRATION_CHARS]
        parts.append(f"   narration: {json.dumps(narration, ensure_ascii=False) if narration else '(none)'}")
    parts += ["", "TRANSCRIPT (verbatim, speech-to-text; may contain errors):", _budget_transcript(transcript_text) or "(no speech)"]
    return "\n".join(parts)


# -------------------------------------------------------------- providers ----


def _max_tokens(n_steps: int) -> int:
    # Adaptive thinking spends from the same cap as the visible output (see
    # rewrite._call_claude), so scale generously and keep a high ceiling.
    return min(32_000, max(16_000, 4_000 + 250 * n_steps))


def _call_anthropic(system: str, prompt: str, max_tokens: int) -> str:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.doc_llm_timeout_s)
    msg = client.messages.create(
        model=s.anthropic_model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "max_tokens":
        raise ValueError("writer output truncated (max_tokens reached)")
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _call_openrouter(system: str, prompt: str, max_tokens: int) -> str:
    import httpx

    s = get_settings()
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {s.openrouter_api_key}", "Content-Type": "application/json"},
        json={
            "model": s.openrouter_model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=s.doc_llm_timeout_s,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_object(text: str) -> dict[str, Any]:
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j < 0:
            raise ValueError("no JSON object in writer output")
        t = t[i : j + 1]
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("writer output is not an object")
    return obj


# ------------------------------------------------------------------ merge ----

_WAIT_ONLY = re.compile(r"^(wait|pause|waiting|loading)[^a-z]*$", re.IGNORECASE)


def merge_model_output(
    parsed: dict[str, Any], steps: list[dict[str, Any]], fallback: dict[str, Any]
) -> dict[str, Any]:
    """Reconcile the model's JSON with the graph. Order and identity come from the
    graph: unknown ids are dropped, duplicates keep the first, a missing REQUIRED
    id gets its mechanical step, an OPTIONAL (silent) step is kept only when the
    model wrote real content for it. When more than half the required steps are
    missing the model ignored the contract; the consistent fallback wins."""
    _, required = _split_steps(steps)
    by_id: dict[str, dict[str, Any]] = {}
    for item in parsed.get("steps") or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if item["id"] in by_id:
            continue
        by_id[item["id"]] = item
    known = {s["id"] for s in steps}
    for unknown in set(by_id) - known:
        log.info("doc writer: dropping unknown step id %r", unknown)

    out_steps: list[dict[str, Any]] = []
    missing = 0
    for s in steps:
        mech = _mechanical_step(s)
        item = by_id.get(s["id"])
        if s["id"] in required:
            if item is None:
                missing += 1
                out_steps.append(mech)
                continue
            title = clean_text(item.get("title"), 200) or mech["title"]
            body = clean_text(item.get("body"), 4000) or mech["body"]
            tip = clean_text(item.get("tip"), 600) if item.get("tip") else None
            out_steps.append({**mech, "title": title, "body": body, "tip": tip or None})
        else:
            if item is None:
                continue
            body = clean_text(item.get("body"), 4000)
            if not body or _WAIT_ONLY.match(body):
                continue
            title = clean_text(item.get("title"), 200) or mech["title"]
            tip = clean_text(item.get("tip"), 600) if item.get("tip") else None
            out_steps.append({**mech, "title": title, "body": body, "tip": tip or None})

    if required and missing > len(required) // 2:
        log.warning("doc writer: model skipped %d of %d required steps; using fallback", missing, len(required))
        return fallback

    def _strs(v: Any) -> list[str]:
        return [x for x in (clean_text(i, 300) for i in (v if isinstance(v, list) else []) if isinstance(i, str)) if x][:20]

    merged = {
        **fallback,
        "title": clean_text(parsed.get("title"), 200) or fallback["title"],
        "overview": clean_text(parsed.get("overview"), 4000) or fallback["overview"],
        "prerequisites": _strs(parsed.get("prerequisites")),
        "steps": out_steps,
        "tips": _strs(parsed.get("tips")),
        "meta": {**fallback["meta"], "writer": "llm", "missing_steps": missing},
    }
    return DocV2.model_validate(merged).model_dump()


# ------------------------------------------------------------------ entry ----


@observe(name="ai-doc-writer")
def write_document(
    *,
    project_title: str,
    transcript_text: str,
    steps: list[dict[str, Any]],
    skill_settings: dict[str, Any] | None = None,
    instruction: str | None = None,
    language: str | None = None,
    graph_version: int | None = None,
    skill_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """LLM-written DocV2 (no snapshots): Anthropic, then OpenRouter, then the
    deterministic fallback. Never raises for provider problems; meta.writer
    records which path produced the text."""
    fallback = write_document_fallback(
        project_title=project_title,
        transcript_text=transcript_text,
        steps=steps,
        instruction=instruction,
        skill_settings=skill_settings,
        graph_version=graph_version,
        now=now,
    )
    fallback["meta"]["skill_id"] = skill_id
    s = get_settings()
    if not steps or not (s.anthropic_api_key or s.openrouter_api_key):
        return fallback
    _, required = _split_steps(steps)
    prompt = _writer_prompt(
        project_title=project_title,
        transcript_text=transcript_text,
        steps=steps,
        required=required,
        skill_settings=skill_settings,
        instruction=instruction,
        language=language,
    )
    max_tokens = _max_tokens(len(steps))
    try:
        if s.anthropic_api_key:
            text, model = _call_anthropic(WRITER_SYSTEM, prompt, max_tokens), s.anthropic_model
        else:
            text, model = _call_openrouter(WRITER_SYSTEM, prompt, max_tokens), s.openrouter_model
        doc = merge_model_output(_parse_object(text), steps, fallback)
        if doc["meta"].get("writer") == "llm":
            doc["meta"]["model"] = model
        return doc
    except Exception as e:  # provider/network/parse — the fallback is the contract
        log.warning("doc writer failed (%s); using deterministic fallback", e)
        return fallback


# ------------------------------------------------------- share fallback ----


def bbox_to_norm(bbox: Any, viewport: dict[str, Any] | None) -> list[float] | None:
    """[x,y,w,h] in viewport px -> normalised 0..1 by the viewport (the same
    convention as the worker's click-centred zoom). None when either is missing."""
    vp = viewport or {}
    vw, vh = vp.get("w") or 0, vp.get("h") or 0
    if not vw or not vh or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    return [
        min(1.0, max(0.0, x / vw)),
        min(1.0, max(0.0, y / vh)),
        min(1.0, max(0.0, w / vw)),
        min(1.0, max(0.0, h / vh)),
    ]


def attach_graph_screenshots(
    doc: dict[str, Any], graph_json: dict[str, Any], viewport: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Fill snapshots from the graph's own keyframes (no ffmpeg). Used for the
    public share fallback when a project has no generated document."""
    by_id = {s["id"]: s for s in graph_json.get("steps", [])}
    for step in doc.get("steps", []):
        g = by_id.get((step.get("source") or {}).get("graph_step_id") or step.get("id"))
        key = (g or {}).get("screenshot")
        if key:
            step["snapshot"] = {
                "key": key,
                "raw_key": key,
                "t": g.get("t_start"),
                "bbox_norm": bbox_to_norm(g.get("bbox"), viewport),
                "pending": False,
            }
    return doc
