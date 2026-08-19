"""The Auto Record driver brain: given the coverage plan, the narration transcript,
the history of actions taken so far, and a fresh observation of the tab, decide the
single next action to perform. The extension is the eyes/hands; this is the mind.

Claude is called with strict tool use (one forced `next_action` tool) so the output
is always a validated action object — never free-form text to parse. The stable
prefix (rules + plan + transcript) is prompt-cached; only the volatile history +
current observation change per step, so every step after the first is a cache read."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.tracing import observe

log = logging.getLogger("refract.agent")

RULES = (
    "You are driving a real, logged-in browser tab that is being screen-recorded to "
    "produce a polished product-demo video. You act one step at a time.\n\n"
    "Principles:\n"
    "- Follow the coverage plan in order: demonstrate each page / feature / operation it "
    "lists. Track which items are done.\n"
    "- Move deliberately, like a human presenter: ONE meaningful UI action per step. Do not "
    "rush or batch unrelated actions.\n"
    "- Only act on elements present in the current observation, referenced by their `ref`.\n"
    "- Never navigate away from the product's own domain. Never type into password fields.\n"
    "- If an element you expected is missing, re-read the new observation and adapt (scroll, "
    "wait, or pick another path). Use `wait` when the page is still loading.\n"
    "- For every action also give a short human `target`, the `intent` (why), the "
    "`screen_name` (which page), and the `plan_item_id` it advances — these become the video's "
    "step labels.\n"
    "- Call `done` only when every coverage-plan item is covered. Call `fail` if you are stuck "
    "and cannot make progress."
)

# The single tool the model must call. Server assigns the step index; the model only
# decides the action.
NEXT_ACTION_TOOL: dict[str, Any] = {
    "name": "next_action",
    "description": "Perform exactly one action on the recorded tab, or end the run.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "progress_note"],
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "input", "scroll", "navigate", "keydown", "wait", "done", "fail"],
            },
            "ref": {"type": "string", "description": "Element ref from the current observation (click/input)."},
            "text": {"type": "string", "description": "Text to type (input)."},
            "url": {"type": "string", "description": "URL to open (navigate)."},
            "key": {"type": "string", "enum": ["Enter", "Escape", "Tab"], "description": "Special key (keydown)."},
            "wait_ms": {"type": "integer", "minimum": 300, "maximum": 5000},
            "scroll_to": {"type": "string", "enum": ["up", "down"]},
            "clear": {"type": "boolean", "description": "Clear the field before typing (input)."},
            "press_enter": {"type": "boolean", "description": "Press Enter after typing (input)."},
            "target": {"type": "string", "description": "Short human label of the element/target."},
            "intent": {"type": "string", "description": "Why this action (one short phrase)."},
            "screen_name": {"type": "string", "description": "The page/screen this happens on."},
            "plan_item_id": {"type": "string", "description": "Which coverage-plan item id this advances."},
            "plan_item_completed": {"type": "boolean", "description": "True if this action completes that plan item."},
            "progress_note": {"type": "string", "description": "One line shown live to the user."},
        },
    },
}


def _elements_summary(elements: list[dict]) -> list[dict]:
    out = []
    for e in elements[:150]:
        out.append(
            {
                k: v
                for k, v in {
                    "ref": e.get("ref"),
                    "tag": e.get("tag"),
                    "role": e.get("role"),
                    "text": (e.get("text") or "")[:80] or None,
                    "value": (e.get("value") or "")[:40] or None,
                    "disabled": e.get("disabled") or None,
                }.items()
                if v is not None
            }
        )
    return out


def _plan_checklist(plan_items: list[dict]) -> str:
    return "\n".join(
        f"- [{('x' if it.get('status') == 'done' else ' ')}] {it.get('id')}: {it.get('text')}"
        for it in plan_items
    )


def _history_text(agent_log: list[dict], limit: int = 40) -> str:
    if not agent_log:
        return "(no actions yet)"
    lines = []
    for e in agent_log[-limit:]:
        status = "ok" if e.get("ok") else f"FAILED: {e.get('error') or 'unknown'}"
        label = e.get("target") or e.get("ref") or e.get("url") or ""
        lines.append(f"{e.get('index')}. {e.get('action')} {label} -> {status}")
    return "\n".join(lines)


def _user_content(run_plan: list[dict], agent_log: list[dict], observation: dict) -> list[dict]:
    obs = {
        "url": observation.get("url"),
        "title": observation.get("title"),
        "scroll_y": observation.get("scroll_y"),
        "scroll_max": observation.get("scroll_max"),
        "elements": _elements_summary(observation.get("elements") or []),
    }
    text = (
        "Coverage plan progress:\n"
        + _plan_checklist(run_plan)
        + "\n\nActions so far:\n"
        + _history_text(agent_log)
        + "\n\nCurrent observation:\n"
        + json.dumps(obs, ensure_ascii=False)
        + "\n\nDecide the single next action."
    )
    content: list[dict] = [{"type": "text", "text": text}]
    shot = observation.get("screenshot_b64")
    if shot:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": shot},
            }
        )
    return content


@observe(name="autorecord-decide")
def decide_next_action(
    *,
    coverage_plan: list[dict],
    transcript: str,
    agent_log: list[dict],
    observation: dict,
) -> dict[str, Any]:
    """Call Claude to choose the next action. Returns the tool input dict.
    Raises RuntimeError when no Anthropic key is configured (Auto Record needs the LLM)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("Auto Record needs an Anthropic API key (set REFRACT_ANTHROPIC_API_KEY)")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120)
    system = [
        {"type": "text", "text": RULES},
        {
            "type": "text",
            "text": (
                "Coverage plan:\n"
                + json.dumps(coverage_plan, ensure_ascii=False)
                + "\n\nNarration transcript (for pacing/context only — do NOT read it aloud, "
                "it is voiced separately):\n"
                + (transcript or "(none)")
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=system,
        tools=[NEXT_ACTION_TOOL],
        tool_choice={"type": "tool", "name": "next_action"},
        messages=[{"role": "user", "content": _user_content(coverage_plan, agent_log, observation)}],
    )
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "next_action":
            return dict(block.input)
    raise RuntimeError("model did not return a next_action tool call")
