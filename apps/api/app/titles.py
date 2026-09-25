"""Project titles from a recording: what the video is *about*, not its first words.

Why this exists: the old fallback (used whenever no LLM key is configured, as on
the ivolve deployment) titled a project with the first six transcript words —
"So Today I Am Going To" — which read as noise.

Order of preference:
1. An LLM (Anthropic, then OpenRouter) given the transcript *and* the detected
   steps (actions, targets, screen names), so it can name the task.
2. `heuristic_title` — deterministic, offline:
   a. the stated goal in the intro ("today I'll show you how to create an API
      key" -> "Create an API Key");
   b. the strongest key phrase of the transcript (RAKE-style: phrases between
      stopwords, scored by word degree/frequency) -> "Payment Gateway Setup";
   c. with no speech, the screens/targets the steps touched -> "Settings Walkthrough".
   Returns "" when there is nothing meaningful, so the caller keeps the name.

Pure functions over plain data (no I/O except the LLM calls) so the heuristic is
exhaustively testable.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

log = logging.getLogger("refract.titles")

MAX_WORDS = 8
MAX_CHARS = 70

FILLERS = {
    "um", "umm", "uh", "uhh", "er", "erm", "ah", "hmm", "okay", "ok", "so", "yeah",
    "basically", "actually", "literally", "like", "right", "alright", "well", "just",
    "now", "here", "there", "hi", "hello", "hey", "everyone", "guys", "folks", "welcome",
}
STOPWORDS = FILLERS | {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "so", "of", "in", "on",
    "at", "to", "for", "with", "from", "by", "as", "into", "onto", "about", "over", "under",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "done",
    "have", "has", "had", "will", "would", "can", "could", "should", "shall", "may",
    "might", "must", "i", "me", "my", "we", "us", "our", "you", "your", "he", "she", "it",
    "its", "they", "them", "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "when", "where", "why", "how", "all", "any", "some", "each", "every",
    "no", "not", "yes", "very", "too", "also", "again", "once", "more", "most", "other",
    "such", "only", "own", "same", "few", "both", "up", "down", "out", "off", "let",
    "let's", "lets", "i'm", "we're", "you're", "it's", "that's", "there's", "we'll",
    "i'll", "you'll", "going", "gonna", "want", "wanna", "need", "see", "look", "looks",
    "show", "shows", "click", "clicking", "clicked", "go", "goes", "get", "got", "make",
    "thing", "things", "something", "stuff", "way", "lot", "bit", "today", "video",
    "recording", "screen", "able", "one", "two", "first", "next", "last", "again", "yeah",
    "know", "think", "say", "said", "tell", "try", "use", "using", "used", "put", "take",
    "come", "came", "give", "keep", "sure", "please", "thank", "thanks", "don't", "can't",
    "won't", "isn't", "doesn't", "didn't", "okay", "time", "page", "button",
    "finally", "press", "pressed", "open", "opened", "select", "selected", "choose",
    "enter", "type", "fill", "called", "check", "shown", "working", "works", "work",
    "happen", "happens", "option", "options", "click", "hit", "scroll", "field",
    "yes", "no", "correct", "fine", "good", "great", "nice", "simple", "basic", "different",
    "current", "new", "particular", "whole", "entire", "actual", "real", "example",
}
# The stated goal must start with a real action (or its -ing form): this is what
# separates "create an API key" from "check now let us what …".
ACTION_VERBS = {
    "add", "analyze", "analyse", "approve", "assign", "automate", "book", "build", "change",
    "compare", "configure", "connect", "convert", "create", "customize", "customise",
    "debug", "delete", "deploy", "design", "disable", "download", "draft", "edit", "enable",
    "explore", "export", "filter", "find", "fix", "generate", "import", "install",
    "integrate", "invite", "launch", "manage", "map", "merge", "migrate", "monitor",
    "onboard", "organize", "organise", "plan", "prepare", "publish", "record", "register",
    "remove", "rename", "report", "reset", "restore", "review", "run", "schedule", "search",
    "send", "set", "setup", "share", "sign", "submit", "sync", "test", "track",
    "troubleshoot", "update", "upgrade", "upload", "validate", "verify", "write",
}
SMALL = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "from", "via"}
GENERIC_SCREENS = {"", "screen", "page", "app", "application", "window", "browser", "untitled"}
_GENERIC_SCREEN = re.compile(r"^(?:screen|page|step|scene|window|tab|view)\s*\d*$", re.IGNORECASE)


def _is_generic_screen(name: str) -> bool:
    n = (name or "").strip()
    return n.lower() in GENERIC_SCREENS or bool(_GENERIC_SCREEN.match(n))


def _is_action(word: str) -> bool:
    w = word.lower()
    if w in ACTION_VERBS:
        return True
    if w.endswith("ing") and len(w) > 5:  # configuring, setting (set+t+ing), creating
        stem = w[:-3]
        return any(v in ACTION_VERBS for v in (stem, stem + "e", stem[:-1] if len(stem) > 2 and stem[-1] == stem[-2] else stem))
    return False


def _plausible(words: list[str]) -> bool:
    """A title-shaped phrase: 2-8 words, mostly content, no word repeated."""
    if not 2 <= len(words) <= MAX_WORDS:
        return False
    low = [w.lower() for w in words]
    if len(set(low)) != len(low):
        return False
    content = [w for w in low if w not in STOPWORDS | SMALL and not w.isdigit()]
    return len(content) >= 2 and len(content) >= len(low) / 2

# "today I'll show you how to create an API key", "we are going to set up …",
# "this video walks through configuring …" — the stated goal of the recording.
_INTENT = re.compile(
    r"\b(?:show(?:ing)? you|walk(?:ing)? (?:you )?through|going to|gonna|want to|we(?:'ll| will)|"
    r"i(?:'ll| will)|let's|let us|learn|explain(?:ing)?|demonstrat(?:e|ing)|cover(?:ing)?|"
    r"see|look at|talk about)\s+"
    r"(?:you\s+)?(?:how\s+(?:to|we|you)\s+(?:can\s+)?)?"
    r"(?P<phrase>[a-z0-9][a-z0-9 '\-/.]{2,80})",
    re.IGNORECASE,
)
_TOPIC_LEAD = re.compile(
    r"\b(?:explain(?:ing)?|cover(?:ing)?|talk(?:ing)? about|demonstrat(?:e|ing)|introduc(?:e|ing)|"
    r"walk(?:ing)? (?:you )?through|take you through|overview of)\b",
    re.IGNORECASE,
)
_CLAUSE_BREAK = re.compile(
    r"\s+(?:and then|and|so|because|which|where|when|while|but|then|after|before|once|"
    r"in this|in the next|for this|first|let's|okay|right)\b|[.,;:!?]",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9'\-/]|\.(?=[A-Za-z0-9]))*")  # inner dots only (v2.0)
# Lead-ins left at the front of an intent phrase ("going to" matched first, so
# "show you how to create …" still carries "show you how to").
_LEAD_IN = re.compile(
    r"^(?:show(?:ing)?(?: you)?|walk(?:ing)?(?: you)? through|take you through|go(?:ing)? through|"
    r"explain(?:ing)?|demonstrat(?:e|ing)|cover(?:ing)?|learn|see|look at|talk about|"
    r"how(?: to| we| you| i)?(?: can| will| would)?|we can|you can|i can|to)\s+",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text or "")  # [music], (inaudible)
    return re.sub(r"\s+", " ", text).strip()


def _cased_vocab(text: str) -> dict[str, str]:
    """How each word was written where it carried capitals mid-sentence
    (API, SAP, iPhone, RevEase) — preserved in the title instead of Title-casing."""
    vocab: dict[str, str] = {}
    for w in _WORD.findall(text):
        if any(c.isupper() for c in w[1:]) or (w.isupper() and len(w) > 1):
            vocab.setdefault(w.lower(), w)
    return vocab


def title_case(words: list[str], vocab: dict[str, str]) -> str:
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in vocab:
            out.append(vocab[lw])
        elif i and lw in SMALL:
            out.append(lw)
        else:  # capitalise each hyphenated part: two-factor -> Two-Factor
            out.append("-".join(part[:1].upper() + part[1:] for part in lw.split("-")))
    return " ".join(out)


def _trim(words: list[str]) -> list[str]:
    """Drop stopwords from both ends and cap the length."""
    words = [w for w in words if w]
    while words and words[0].lower() in STOPWORDS and words[0].lower() not in {"how"}:
        words = words[1:]
    words = words[:MAX_WORDS]
    while words and words[-1].lower() in STOPWORDS | SMALL:
        words = words[:-1]
    return words


def _intent_phrase(text: str) -> list[str]:
    """The stated goal from the first ~80 words, or []."""
    head = " ".join(text.split()[:80])
    for m in _INTENT.finditer(head):
        # "explain / cover / talk about / walk through <topic>" introduces a subject
        # rather than an action, so a noun phrase is acceptable after those.
        topical = bool(_TOPIC_LEAD.search(m.group(0)))
        phrase = m.group("phrase")
        for _ in range(4):  # peel stacked lead-ins: "show you how to …"
            stripped = _LEAD_IN.sub("", phrase, count=1)
            if stripped == phrase:
                break
            phrase = stripped
        phrase = _CLAUSE_BREAK.split(phrase, maxsplit=1)[0]
        words = _WORD.findall(phrase)
        while words and words[0].lower() in SMALL | {"the", "a", "an", "our", "your", "my", "this"}:
            words = words[1:]
        words = words[:MAX_WORDS]
        while words and words[-1].lower() in STOPWORDS | SMALL:
            words = words[:-1]
        if words and _plausible(words) and (_is_action(words[0]) or topical or _TOPIC_LEAD.match(" ".join(m.group("phrase").split()[:3]))):
            return words
    return []


def _key_phrase(text: str) -> list[str]:
    """RAKE-style: candidate phrases are runs of non-stopwords; a phrase scores the
    sum of its words' degree/frequency, boosted when the phrase recurs."""
    tokens = [w for w in _WORD.findall(text.lower())]
    phrases: list[tuple[str, ...]] = []
    cur: list[str] = []
    for t in tokens:
        if t in STOPWORDS or t.isdigit() or len(t) < 2:
            if cur:
                phrases.append(tuple(cur))
            cur = []
        else:
            cur.append(t)
    if cur:
        phrases.append(tuple(cur))
    phrases = [p[:4] for p in phrases if p]
    if not phrases:
        return []
    freq: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    for p in phrases:
        for w in p:
            freq[w] += 1
            degree[w] += len(p) - 1
    word_score = {w: (degree[w] + freq[w]) / freq[w] for w in freq}
    # Recurrence is counted on 2-3 word sub-phrases: "payment gateway" recurs even
    # when every mention sits inside a different longer run.
    grams: Counter[tuple[str, ...]] = Counter()
    for p in phrases:
        for n in (2, 3):
            for i in range(len(p) - n + 1):
                grams[p[i:i + n]] += 1
    recurring = [g for g, c in grams.items() if c >= 2 and _plausible(list(g))]
    if not recurring:
        return []
    best = max(recurring, key=lambda g: (grams[g], sum(word_score[w] for w in g), len(g)))
    return list(best)


def _steps_phrase(steps: list[dict[str, Any]]) -> list[str]:
    screens = Counter(
        (s.get("screen_name") or "").strip() for s in steps
        if not _is_generic_screen(s.get("screen_name") or "")
    )
    if screens:
        name, _ = screens.most_common(1)[0]
        return _WORD.findall(name)[:4]
    targets = Counter()
    for s in steps:
        t = (s.get("target") or "").strip()
        words = [w for w in _WORD.findall(t) if not w.isdigit()]
        if len(words) >= 2 and not t.lower().startswith(("silence", "the element")):
            targets[t] += 1
    if targets:
        name, n = targets.most_common(1)[0]
        if n >= 2:  # the recording keeps returning to it
            return _trim(_WORD.findall(name))[:4]
    return []


def heuristic_title(transcript: str, steps: list[dict[str, Any]] | None = None) -> str:
    text = _clean(transcript)
    vocab = _cased_vocab(text)
    words = _intent_phrase(text) if text else []
    if words:
        return title_case(words, vocab)[:MAX_CHARS]
    words = _key_phrase(text) if text else []
    if words:
        return title_case(words, vocab)[:MAX_CHARS]
    words = _steps_phrase(steps or [])
    if words:
        return title_case(words + ["Walkthrough"], _cased_vocab(" ".join(words)))[:MAX_CHARS]
    return ""


# ------------------------------------------------------------------ LLM ----

TITLE_SYSTEM = (
    "You name screen recordings of software workflows so a colleague can find them later. "
    "Given the narration transcript and the list of recorded steps, write the task the "
    "recording demonstrates, as a title: 3 to 7 words, Title Case, starting with the "
    "action when there is a clear task (\"Create an API Key in Settings\"), otherwise the "
    "topic (\"Payment Gateway Overview\"). Keep product and feature names exactly as "
    "written. Never start with filler (\"So Today\", \"In This Video\") and never use "
    "the words Video, Recording, Tutorial or Demo. Reply with ONLY the title."
)


def _steps_summary(steps: list[dict[str, Any]], limit: int = 25) -> str:
    lines = []
    for s in steps[:limit]:
        target = (s.get("target") or "").strip()
        if not target or target.lower().startswith("silence"):
            continue
        screen = (s.get("screen_name") or "").strip()
        action = s.get("action") or "custom"
        lines.append(f"- {action} {target}" + (f" (on {screen})" if screen and screen.lower() not in GENERIC_SCREENS else ""))
    return "\n".join(lines) or "(no clicks recorded)"


def _sanitize(title: str) -> str:
    t = (title or "").strip().splitlines()[0] if (title or "").strip() else ""
    t = re.sub(r"^\W*title\s*:\s*", "", t, flags=re.IGNORECASE)
    for _ in range(2):  # quotes/markup may wrap a trailing period: "Title."
        t = t.strip().strip('"\'`*#').strip().rstrip(".")
    return t[:MAX_CHARS]


def llm_title(transcript: str, steps: list[dict[str, Any]]) -> str:
    """Anthropic, then OpenRouter. Returns "" when no provider is configured or all fail."""
    from app.config import get_settings

    s = get_settings()
    prompt = f"Recorded steps:\n{_steps_summary(steps)}\n\nTranscript:\n{(transcript or '(no speech)')[:6000]}"
    if s.anthropic_api_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=60)
            msg = client.messages.create(model=s.anthropic_model, max_tokens=2000,
                                         system=TITLE_SYSTEM, messages=[{"role": "user", "content": prompt}])
            out = _sanitize("".join(b.text for b in msg.content if getattr(b, "type", None) == "text"))
            if out:
                return out
        except Exception as e:  # pragma: no cover - network
            log.warning("anthropic title failed (%s)", e)
    if s.openrouter_api_key:
        try:
            import httpx

            r = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.openrouter_api_key}"},
                json={"model": s.openrouter_model, "temperature": 0.2, "max_tokens": 40,
                      "messages": [{"role": "system", "content": TITLE_SYSTEM},
                                   {"role": "user", "content": prompt}]},
                timeout=60,
            )
            r.raise_for_status()
            out = _sanitize(r.json()["choices"][0]["message"]["content"])
            if out:
                return out
        except Exception as e:  # pragma: no cover - network
            log.warning("openrouter title failed (%s)", e)
    return ""


def project_title(transcript: str, steps: list[dict[str, Any]] | None = None) -> str:
    """The best available title, or "" (caller keeps the current name)."""
    return suggest_title(transcript, steps)[0]


def suggest_title(transcript: str, steps: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """(title, source) with source "llm" | "heuristic" | "". Callers let an LLM
    title replace any name but a heuristic one only replace a placeholder."""
    steps = steps or []
    if not (transcript or "").strip() and not steps:
        return "", ""
    t = llm_title(transcript, steps)
    if t:
        return t, "llm"
    t = heuristic_title(transcript, steps)
    return (t, "heuristic") if t else ("", "")


_PLACEHOLDER = re.compile(
    r"^screen recording\b|^(?:untitled|new project|new recording|recording|upload(?:ed)?(?: video)?)$"
    r"|\d{4}-\d{2}-\d{2}|\b\d{1,2}[:.]\d{2}\b|\bat \d{1,2}\b",
    re.IGNORECASE,
)


def is_placeholder_name(name: str) -> bool:
    """Names the app or the OS gave automatically ("Screen Recording · 4 Sept,
    09:54", "Screen Recording 2026-09-24 at 3.16 PM") — safe to replace."""
    return not (name or "").strip() or bool(_PLACEHOLDER.search(name))
