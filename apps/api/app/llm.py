"""One text-completion call for every AI feature: Anthropic when an Anthropic key
is configured, otherwise OpenRouter, otherwise `NoLLMConfigured`.

Why this exists: most features used to call the Anthropic SDK directly and only
checked that *some* key was set. When the ivolve deployment had an OpenRouter
key (sk-or-…) in REFRACT_ANTHROPIC_API_KEY, every call failed with 401 and each
feature silently fell back to its offline heuristic — project titles became the
first words of the transcript. Settings now moves such a key to the OpenRouter
slot (see config.py), and this module makes OpenRouter a real path for all of
them.

Callers keep their own prompts and parsing; they only swap the transport.
"""

from __future__ import annotations

import logging

from app.config import get_settings

log = logging.getLogger("refract.llm")

# OpenRouter has no adaptive-thinking budget sharing the cap, so a smaller
# ceiling is plenty for the visible output.
OPENROUTER_MAX_TOKENS = 8000


class NoLLMConfigured(RuntimeError):
    pass


def has_llm() -> bool:
    s = get_settings()
    return bool(s.anthropic_api_key or s.openrouter_api_key)


def provider_name() -> str:
    s = get_settings()
    if s.anthropic_api_key:
        return f"anthropic:{s.anthropic_model}"
    if s.openrouter_api_key:
        return f"openrouter:{s.openrouter_model}"
    return "none"


def complete(system: str, prompt: str, *, max_tokens: int = 16000, timeout: float = 120) -> str:
    """The model's text reply. Raises NoLLMConfigured when no key is set, and
    ValueError when the reply was cut off at max_tokens."""
    s = get_settings()
    if s.anthropic_api_key:
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=timeout)
        # Adaptive thinking spends from the same cap as the visible output —
        # keep the ceiling high (it is a ceiling, not a spend).
        msg = client.messages.create(
            model=s.anthropic_model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            system=system, messages=[{"role": "user", "content": prompt}],
        )
        if msg.stop_reason == "max_tokens":
            raise ValueError("model output was truncated (max_tokens reached) — try again")
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    if s.openrouter_api_key:
        import httpx

        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {s.openrouter_api_key}", "Content-Type": "application/json"},
            json={"model": s.openrouter_model, "max_tokens": min(max_tokens, OPENROUTER_MAX_TOKENS),
                  "temperature": 0.2,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
            timeout=timeout,
        )
        r.raise_for_status()
        choice = r.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("model output was truncated (max_tokens reached) — try again")
        return choice["message"]["content"] or ""
    raise NoLLMConfigured("no AI key configured (set REFRACT_ANTHROPIC_API_KEY or REFRACT_OPENROUTER_API_KEY)")
