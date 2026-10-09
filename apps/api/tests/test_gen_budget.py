"""Generate must not write more than a scene's footage can carry: the render
freezes the last frame while the voice finishes, which is what users noticed.
Budgets are explicit word caps; overruns get one shorten pass, then a trim at a
sentence boundary."""

from __future__ import annotations

import json

from app import rewrite
from app.rewrite import enforce_budgets, fit_to_budget, scene_word_budget


def test_budget_from_seconds_leaves_room_for_the_scene_gap():
    assert scene_word_budget(10) == 21  # (10 - 0.8) * 2.3
    assert scene_word_budget(10, speed=1.3) == 27  # faster voice, more words
    assert scene_word_budget(0.8) == 0 and scene_word_budget(0) == 0
    assert scene_word_budget(2) == 2


def test_fit_to_budget_drops_whole_sentences_only():
    line = "Open the dashboard. Then pick an invoice to view. Finally export it."
    assert fit_to_budget(line, 9) == "Open the dashboard. Then pick an invoice to view."
    assert fit_to_budget(line, 8) == "Open the dashboard."  # 3 + 6 words would be 9
    assert fit_to_budget(line, 3) == "Open the dashboard."
    assert fit_to_budget(line, 1) == "Open the dashboard."  # never cuts inside a sentence
    assert fit_to_budget(line, 0) == ""
    assert fit_to_budget("Short line.", 5) == "Short line."


def test_enforce_budgets_shortens_then_trims(monkeypatch):
    asked: list[dict] = []

    def fake_complete(system, prompt, **kw):
        items = json.loads(prompt.split("\n", 1)[1])
        asked.extend(items)
        # obeys for the first, ignores the limit for the second
        return json.dumps(["Open the invoices tab.", "Still far too long a sentence here. And another one."])

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", fake_complete)
    lines = ["Open the invoices tab to see every invoice your team has.", "fits", "A very long line indeed, is it not."]
    out = enforce_budgets(lines, [4, None, 5])
    assert [a["max_words"] for a in asked] == [4, 5]  # only the overruns go back
    assert out[0] == "Open the invoices tab."
    assert out[1] == "fits"
    assert out[2] == "Still far too long a sentence here."  # trimmed to a sentence


def test_generate_script_tells_the_model_the_cap_and_keeps_user_lines(monkeypatch):
    seen: list[str] = []

    def fake_complete(system, prompt, **kw):
        seen.append(prompt)
        if system is rewrite.SHORTEN_SYSTEM:
            return json.dumps(["Click Create."])
        return json.dumps(["Click Create and the suite is ready to run under Test Execution.", "x"])

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", fake_complete)
    scenes = [
        {"target": "Create", "action": "click", "narration": "", "seconds": 2, "max_words": 3},
        {"target": "t", "action": "custom", "narration": "", "seconds": 4},
    ]
    out = rewrite.generate_script(scenes)
    first = json.loads(seen[0].split("Scenes:\n", 1)[1])
    assert first[0]["max_words"] == 3 and first[1]["max_words"] == scene_word_budget(4)
    assert "seconds" not in first[0]
    assert out == ["Click Create.", "x"]
