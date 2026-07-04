"""Auto Record narration alignment: split the user's free-text transcript into one
narration span per step.

For a manual recording, narration comes from Whisper (word timings -> per-step
spans). An Auto Record run has no spoken audio — the user supplied the transcript
as text. So we must partition that transcript across the driven steps, in order,
keeping every word VERBATIM (the on-screen script and the TTS voice must match the
transcript word-for-word — the same invariant `providers.label_steps` enforces).

Strategy: ask Claude to assign a contiguous, in-order, possibly-empty slice of the
transcript to each step (anchored by each step's plan item + intent). The result is
hard-validated to be a verbatim partition; on any failure we fall back to a
deterministic even split. Either way the output length == number of steps.
"""

from __future__ import annotations

import json
import logging
import re

from app.config import get_settings
from app.tracing import observe as _observe

log = logging.getLogger("refract.pipeline.narrate")


def _words(s: str) -> list[str]:
    return (s or "").split()


def _sentences(text: str) -> list[str]:
    """Split into sentences, preserving words (used by the deterministic fallback)."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _even_split(text: str, n: int) -> list[str]:
    """Deterministic fallback: distribute the transcript's sentences across `n`
    steps in contiguous, proportional chunks (empty chunks allowed when n > #sentences).
    Guaranteed to be a verbatim partition."""
    if n <= 0:
        return []
    sents = _sentences(text)
    if not sents:
        return [""] * n
    out: list[str] = []
    m = len(sents)
    for i in range(n):
        lo = round(i * m / n)
        hi = round((i + 1) * m / n)
        out.append(" ".join(sents[lo:hi]).strip())
    return out


def _is_verbatim_partition(segments: list[str], transcript: str) -> bool:
    """Non-empty segments, concatenated in order, must equal the transcript word-for-word."""
    joined = " ".join(s for s in segments if s and s.strip())
    return _words(joined) == _words(transcript)


ALIGN_SYSTEM = (
    "You align a product-demo narration script to the ordered steps the demo performs. "
    "You receive the full transcript and a numbered list of steps (each with what it does "
    "and which coverage-plan item it belongs to). Split the transcript into exactly one "
    "contiguous slice per step, IN ORDER, so that concatenating all slices reproduces the "
    "transcript EXACTLY — every word, verbatim, nothing added, removed, reworded, or "
    "reordered. A step may get an empty string when no narration belongs to it (e.g. a "
    "setup click between sentences). Put any intro before the first meaningful step on "
    "step 1, and any closing remarks on the last step."
)


def _align_prompt(steps: list[dict], plan_items: list[dict], transcript: str) -> str:
    numbered = [
        {
            "step": i + 1,
            "action": s.get("action"),
            "does": s.get("intent") or s.get("target"),
            "plan_item": s.get("plan_item_id"),
        }
        for i, s in enumerate(steps)
    ]
    return (
        "Coverage plan:\n"
        + json.dumps(plan_items, ensure_ascii=False)
        + f"\n\nTranscript (verbatim, {len(_words(transcript))} words):\n"
        + json.dumps(transcript, ensure_ascii=False)
        + f"\n\nSteps ({len(steps)}):\n"
        + json.dumps(numbered, ensure_ascii=False)
        + "\n\nReply with ONLY a JSON array of exactly "
        + str(len(steps))
        + " strings (no prose, no code fences) — one narration slice per step, same order."
    )


def _parse_array(content: str, n: int) -> list[str]:
    t = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    arr = json.loads(t)
    if not isinstance(arr, list) or len(arr) != n:
        raise ValueError(f"expected {n} narration slices, got {len(arr) if isinstance(arr, list) else '?'}")
    return [str(x) for x in arr]


def _claude_align(steps: list[dict], plan_items: list[dict], transcript: str) -> list[str]:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    prompt = _align_prompt(steps, plan_items, transcript)
    for attempt in range(2):
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=min(16000, 2000 + len(_words(transcript)) * 3),
            thinking={"type": "adaptive"},
            system=ALIGN_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        segments = _parse_array(text, len(steps))
        if _is_verbatim_partition(segments, transcript):
            return [s.strip() for s in segments]
        log.warning("narration alignment not verbatim (attempt %d); retrying", attempt + 1)
        prompt = (
            _align_prompt(steps, plan_items, transcript)
            + "\n\nYour previous answer changed or dropped words. The concatenation of your "
            "slices MUST equal the transcript exactly. Try again."
        )
    raise ValueError("alignment failed verbatim check twice")


@_observe(name="narrate-align")
def narrate_steps(steps: list[dict], plan_items: list[dict], transcript: str) -> list[str]:
    """Return one narration string per step (same order). Verbatim partition of the
    transcript; deterministic even split when there is no API key or the model fails."""
    n = len(steps)
    if n == 0:
        return []
    transcript = (transcript or "").strip()
    if not transcript:
        return [""] * n
    settings = get_settings()
    if settings.anthropic_api_key:
        try:
            return _claude_align(steps, plan_items, transcript)
        except Exception as e:
            log.warning("Claude narration alignment failed (%s); using even split.", e)
    return _even_split(transcript, n)
