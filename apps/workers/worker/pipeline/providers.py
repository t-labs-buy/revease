"""Adapters for the two external-ish dependencies of the understanding pipeline:
speech-to-text and the LLM labeler. Both degrade gracefully so the whole pipeline
runs offline (no GPU, no API key) with deterministic output, and uses the real
provider when configured — the seam the master plan calls for."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.tracing import observe as _observe

log = logging.getLogger("refract.pipeline.providers")


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #
@dataclass
class Word:
    w: str
    t_start: float
    t_end: float


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    text: str = ""
    provider: str = "none"

    def span(self, t0: float, t1: float) -> str:
        """Words whose start falls in [t0, t1) joined into a narration span."""
        return " ".join(w.w for w in self.words if t0 <= w.t_start < t1).strip()


def transcribe(audio_path: str | None) -> Transcript:
    """Word-level transcript via faster-whisper if available + audio present;
    otherwise an empty transcript (segmentation then falls back to scene/time)."""
    import os.path

    settings = get_settings()
    if not audio_path or not os.path.exists(audio_path):
        return Transcript(provider="none")
    if settings.disable_whisper:  # deterministic/fast tests
        return Transcript(provider="none")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        log.info("faster-whisper not installed; skipping transcription (empty transcript).")
        return Transcript(provider="none")

    model_size = settings.whisper_model
    device = settings.whisper_device
    compute = settings.whisper_compute
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute)
        segments, _info = model.transcribe(
            audio_path,
            word_timestamps=True,
            beam_size=5,
            # Voice-activity filter: drop non-speech so Whisper doesn't hallucinate
            # words during the long silent stretches common in screen recordings.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            # Don't feed prior text back in — prevents repetition/drift so the
            # transcript matches what was actually said.
            condition_on_previous_text=False,
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(w=w.word.strip(), t_start=float(w.start), t_end=float(w.end)))
        return Transcript(words=words, text=" ".join(x.w for x in words), provider=f"whisper:{model_size}")
    except Exception as e:  # pragma: no cover - env dependent
        log.warning("Whisper transcription failed (%s); using empty transcript.", e)
        return Transcript(provider="none")


# --------------------------------------------------------------------------- #
# LLM labeler
# --------------------------------------------------------------------------- #
LABEL_SYSTEM = (
    "You label steps of a software workflow. For each input step you receive its "
    "action type, target label/selector, and any narration span from the transcript. "
    "Return concise, user-facing labels."
)


def _fallback_label(step: dict) -> dict:
    """Deterministic labeler used when no API key is configured. Produces the same
    shape the LLM returns, so the rest of the pipeline is provider-agnostic."""
    action = step.get("action", "custom")
    target = (step.get("target") or step.get("selector") or "the element").strip()
    verb = {
        "click": "Click",
        "input": "Type into",
        "navigation": "Go to",
        "scroll": "Scroll",
        "keydown": "Press a shortcut on",
    }.get(action, "Interact with")
    # Narration is ONLY ever the transcript span — never an invented sentence —
    # so the script always matches the spoken audio word-for-word. A silent step
    # gets an empty script (the render plays it at natural speed, silent).
    narration = (step.get("narration_span") or "").strip()
    return {
        "action": action,
        "target": target[:120],
        "intent": f"{verb} {target}"[:160],
        "screen_name": step.get("screen_name") or "Screen",
        "narration": narration,
    }


def _label_prompt(steps: list[dict]) -> str:
    return (
        "Label these workflow steps. Reply ONLY with a JSON array (no prose, no code "
        'fences); each item: {"action","target","intent","screen_name"}. '
        "Do NOT write narration — the narration comes verbatim from the transcript.\n\n"
        + json.dumps(steps, ensure_ascii=False)
    )


def _parse_label_array(content: str, n: int) -> list[dict]:
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    labeled = json.loads(content)
    if not isinstance(labeled, list) or len(labeled) != n:
        raise ValueError("LLM returned wrong shape")
    return labeled


def _anthropic_label(steps: list[dict], api_key: str, model: str) -> list[dict]:
    """Label via the Anthropic API directly (official SDK)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    max_tokens = min(16000, 512 + len(steps) * 160)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=LABEL_SYSTEM,
        messages=[{"role": "user", "content": _label_prompt(steps)}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return _parse_label_array(text, len(steps))


def _openrouter_label(steps: list[dict], api_key: str, model: str) -> list[dict]:
    import httpx

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": LABEL_SYSTEM},
                {"role": "user", "content": _label_prompt(steps)},
            ],
            "temperature": 0.2,
        },
        timeout=90,
    )
    resp.raise_for_status()
    return _parse_label_array(resp.json()["choices"][0]["message"]["content"], len(steps))


@_observe(name="label-steps")
def label_steps(steps: list[dict]) -> list[dict]:
    """Label + narrate each step. Prefers a direct Anthropic key (Claude), then
    OpenRouter, then a deterministic offline labeler. Merges the model's output
    onto the fallback so any missing field degrades gracefully."""
    if not steps:
        return []
    settings = get_settings()
    try:
        if settings.anthropic_api_key:
            labeled = _anthropic_label(steps, settings.anthropic_api_key, settings.anthropic_model)
        elif settings.openrouter_api_key:
            labeled = _openrouter_label(steps, settings.openrouter_api_key, settings.openrouter_model)
        else:
            return [_fallback_label(s) for s in steps]
        merged = []
        for s, lab in zip(steps, labeled):
            row = {**_fallback_label(s), **{k: v for k, v in lab.items() if v}}
            # Narration stays VERBATIM from the transcript so the on-screen script
            # matches the spoken audio word-for-word — ALWAYS, even when the span is
            # empty. The LLM may relabel action/target/intent/screen_name only.
            row["narration"] = (s.get("narration_span") or "").strip()
            merged.append(row)
        return merged
    except Exception as e:
        log.warning("LLM labeling failed (%s); using deterministic fallback.", e)
        return [_fallback_label(s) for s in steps]
