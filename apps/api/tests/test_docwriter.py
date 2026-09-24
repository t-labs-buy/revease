"""Documentation writer: deterministic fallback, model-output reconciliation and
the provider ladder — all offline (conftest strips API keys)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app import docwriter
from app.docwriter import (
    MAX_TRANSCRIPT_CHARS,
    _budget_transcript,
    effective_narrations,
    is_silent,
    merge_model_output,
    write_document,
    write_document_fallback,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

STEPS = [
    {"id": "s1", "action": "click", "target": "Settings → API Keys", "intent": "open the api keys page",
     "narration": "um so first we go to settings and open api keys", "t_start": 0.0, "t_end": 4.2, "bbox": [1, 2, 3, 4]},
    {"id": "s2", "action": "custom", "target": "Silence — add narration", "narration": "", "t_start": 4.2,
     "t_end": 9.0, "bbox": None},
    {"id": "s3", "action": "input", "target": "Key name", "intent": "", "narration": "give it a name like production",
     "t_start": 9.0, "t_end": 14.5, "bbox": [5, 5, 50, 20]},
]


def test_is_silent_detects_filler_and_empty_custom_steps():
    assert is_silent(STEPS[1])
    assert not is_silent(STEPS[0])
    assert is_silent({"action": "custom", "target": "x", "narration": "", "bbox": None})
    assert not is_silent({"action": "custom", "target": "x", "narration": "", "bbox": [1, 1, 1, 1]})


def test_fallback_is_deterministic_and_skips_silence():
    kw = dict(project_title="Create an API key", transcript_text="First we open settings. Then we make a key. Done! Extra.",
              steps=STEPS, graph_version=3, now=NOW)
    a = write_document_fallback(**kw)
    b = write_document_fallback(**kw)
    assert a == b
    assert a["version"] == 2 and a["meta"]["writer"] == "fallback" and a["meta"]["graph_version"] == 3
    assert [s["id"] for s in a["steps"]] == ["s1", "s3"]
    assert a["steps"][0]["title"] == "Open the api keys page"  # sentence-cased intent
    assert a["steps"][0]["body"] == "First we go to settings and open api keys."  # fillers struck
    assert a["steps"][1]["title"] == "Type into Key name"  # verb map when no intent
    assert a["overview"] == "First we open settings. Then we make a key. Done!"
    assert a["steps"][0]["source"] == {"graph_step_id": "s1", "t_start": 0.0, "t_end": 4.2}


def test_fallback_keeps_all_steps_when_every_step_is_silent():
    silent = [{"id": "a", "action": "custom", "target": "Silence — add narration", "narration": ""},
              {"id": "b", "action": "custom", "target": "Silence — add narration", "narration": ""}]
    d = write_document_fallback(project_title="", transcript_text="", steps=silent, now=NOW)
    assert [s["id"] for s in d["steps"]] == ["a", "b"] and d["title"] == "Workflow"
    assert "2 steps" in d["overview"]


def test_effective_narrations_prefers_video_editor_edits():
    graph = {"steps": [{"id": "s1", "narration": "um click save"}, {"id": "s2", "narration": "then done"}]}
    spec = {"segments": [{"step_id": "s1", "words": ["Press", "the", "Save", "button"], "removed": []}]}
    out = effective_narrations(graph, spec)
    assert out["s1"] == "Press the Save button."
    assert out["s2"] == "Then done."


def test_merge_model_output_reconciles_with_graph_order():
    fallback = write_document_fallback(project_title="P", transcript_text="", steps=STEPS, now=NOW)
    parsed = {
        "title": "Create an API key",
        "overview": "Make a key.",
        "prerequisites": ["An admin account", 42],
        "steps": [
            {"id": "s3", "title": "Name the key", "body": "Type `production` in **Key name**.", "tip": "Keep it short."},
            {"id": "zzz", "title": "made up", "body": "nope"},
            {"id": "s3", "title": "dupe", "body": "ignored"},
            {"id": "s2", "title": "Wait", "body": "wait..."},
        ],
        "tips": ["Copy it once."],
    }
    m = merge_model_output(parsed, STEPS, fallback)
    assert [s["id"] for s in m["steps"]] == ["s1", "s3"]  # graph order; unknown + wait-only dropped
    assert m["steps"][0]["body"] == fallback["steps"][0]["body"]  # missing s1 -> mechanical text
    assert m["steps"][1]["title"] == "Name the key" and m["steps"][1]["tip"] == "Keep it short."
    assert m["prerequisites"] == ["An admin account"] and m["tips"] == ["Copy it once."]
    assert m["meta"]["writer"] == "llm" and m["meta"]["missing_steps"] == 1


def test_merge_keeps_optional_step_with_real_content():
    fallback = write_document_fallback(project_title="P", transcript_text="", steps=STEPS, now=NOW)
    parsed = {"steps": [
        {"id": "s1", "title": "Open keys", "body": "Open **API Keys**."},
        {"id": "s2", "title": "Wait for the page", "body": "The API Keys page loads and lists existing keys."},
        {"id": "s3", "title": "Name it", "body": "Type a name."},
    ]}
    m = merge_model_output(parsed, STEPS, fallback)
    assert [s["id"] for s in m["steps"]] == ["s1", "s2", "s3"]


def test_merge_falls_back_wholesale_when_most_steps_missing():
    steps = STEPS + [{"id": "s4", "action": "click", "target": "Save", "narration": "save it"}]
    fallback = write_document_fallback(project_title="P", transcript_text="", steps=steps, now=NOW)
    parsed = {"title": "Only one", "steps": [{"id": "s1", "title": "t", "body": "b"}]}
    assert merge_model_output(parsed, steps, fallback) == fallback


def test_write_document_without_key_uses_fallback():
    d = write_document(project_title="P", transcript_text="", steps=STEPS, now=NOW, skill_id="sk1")
    assert d["meta"]["writer"] == "fallback" and d["meta"]["skill_id"] == "sk1"


def test_write_document_uses_model_when_keyed(monkeypatch):
    fake = {"title": "Create an API key", "overview": "Make a key.", "prerequisites": [],
            "steps": [{"id": "s1", "title": "Open the API Keys page", "body": "Click **Settings**.", "tip": None},
                      {"id": "s3", "title": "Name the key", "body": "Type `production`.", "tip": None}],
            "tips": []}
    calls: list[str] = []

    def fake_call(system, prompt, max_tokens):
        calls.append(prompt)
        assert "id=s1 REQUIRED" in prompt and "id=s2 OPTIONAL" in prompt
        assert "STYLE GUIDE" in prompt and "Overall: Be terse" in prompt
        assert "ADDITIONAL INSTRUCTION FROM THE USER:\nFor admins" in prompt
        return "```json\n" + json.dumps(fake) + "\n```"

    monkeypatch.setattr(docwriter, "_call_anthropic", fake_call)
    monkeypatch.setattr(docwriter, "get_settings", lambda: SimpleNamespace(
        anthropic_api_key="k", openrouter_api_key="", anthropic_model="m", openrouter_model="o", doc_llm_timeout_s=1))
    skill = {"overall_instructions": "Be terse", "sections": [{"title": "Steps", "description": "numbered", "include_screenshots": True}]}
    d = write_document(project_title="P", transcript_text="hello", steps=STEPS, instruction="For admins",
                       skill_settings=skill, now=NOW)
    assert len(calls) == 1
    assert d["meta"]["writer"] == "llm" and d["meta"]["model"] == "m"
    assert d["title"] == "Create an API key" and d["steps"][0]["body"] == "Click **Settings**."


def test_write_document_falls_back_when_model_fails(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(docwriter, "_call_anthropic", boom)
    monkeypatch.setattr(docwriter, "get_settings", lambda: SimpleNamespace(
        anthropic_api_key="k", openrouter_api_key="", anthropic_model="m", openrouter_model="o", doc_llm_timeout_s=1))
    d = write_document(project_title="P", transcript_text="", steps=STEPS, now=NOW)
    assert d["meta"]["writer"] == "fallback"


def test_skill_can_switch_snapshots_off():
    skill = {"sections": [{"title": "Procedure", "description": "", "include_screenshots": False}]}
    d = write_document_fallback(project_title="P", transcript_text="", steps=STEPS, skill_settings=skill, now=NOW)
    assert d["meta"]["snapshots"] is False


def test_transcript_budget_keeps_head_and_tail():
    text = "a" * (MAX_TRANSCRIPT_CHARS + 5000)
    out = _budget_transcript(text)
    assert len(out) < len(text) and "characters omitted" in out
    assert _budget_transcript("short") == "short"
