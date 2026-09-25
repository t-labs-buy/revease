"""AI transport: a misplaced OpenRouter key is re-routed, and OpenRouter is a
real path for every feature (not only Anthropic)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import llm
from app.config import Settings


def test_openrouter_key_in_the_anthropic_slot_is_rerouted():
    s = Settings(anthropic_api_key="sk-or-v1-abc", openrouter_api_key="")
    assert s.anthropic_api_key == "" and s.openrouter_api_key == "sk-or-v1-abc"
    both = Settings(anthropic_api_key="sk-or-v1-abc", openrouter_api_key="sk-or-v1-real")
    assert both.anthropic_api_key == "" and both.openrouter_api_key == "sk-or-v1-real"
    real = Settings(anthropic_api_key="sk-ant-xyz")
    assert real.anthropic_api_key == "sk-ant-xyz"


def _settings(**kw):
    base = dict(anthropic_api_key="", anthropic_model="m", openrouter_api_key="", openrouter_model="o")
    return SimpleNamespace(**{**base, **kw})


def test_complete_uses_openrouter_when_that_is_the_only_key(monkeypatch):
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, auth=headers["Authorization"], body=json)
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"choices": [{"finish_reason": "stop", "message": {"content": "hello"}}]})

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(openrouter_api_key="sk-or-k"))
    assert llm.has_llm() and llm.provider_name() == "openrouter:o"
    assert llm.complete("sys", "hi", max_tokens=16000) == "hello"
    assert sent["url"].startswith("https://openrouter.ai/") and sent["auth"] == "Bearer sk-or-k"
    assert sent["body"]["max_tokens"] == llm.OPENROUTER_MAX_TOKENS
    assert sent["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_complete_reports_truncation_and_missing_keys(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"choices": [{"finish_reason": "length", "message": {"content": "par"}}]}))
    monkeypatch.setattr(llm, "get_settings", lambda: _settings(openrouter_api_key="k"))
    with pytest.raises(ValueError):
        llm.complete("s", "p")
    monkeypatch.setattr(llm, "get_settings", lambda: _settings())
    assert not llm.has_llm()
    with pytest.raises(llm.NoLLMConfigured):
        llm.complete("s", "p")


def test_rewrite_works_through_openrouter(monkeypatch):
    from app import rewrite

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", lambda system, prompt, **kw: '["Open the Settings page."]')
    assert rewrite.rewrite_lines(["um so open settings"]) == ["Open the Settings page."]


def test_zoom_suggestions_never_dead_end(monkeypatch):
    from app import rewrite

    scenes = [
        {"target": "Save button", "action": "click", "narration": "now save"},
        {"target": "Welcome", "action": "custom", "narration": "welcome to the overview"},
        {"target": "", "action": "custom", "narration": "notice the total here"},
        {"target": "Silence — add narration", "action": "custom", "narration": ""},
    ]
    monkeypatch.setattr(rewrite, "has_llm", lambda: False)
    zooms, source = rewrite.suggest_zooms_with_source(scenes)
    assert source == "rules"
    assert [z["zoom"] for z in zooms] == [True, False, True, False]
    assert zooms[0]["scale"] == 1.8  # short target = small on screen

    def boom(*_a, **_kw):
        raise RuntimeError("401 API key is invalid")

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", boom)
    assert rewrite.suggest_zooms_with_source(scenes)[1] == "rules"  # a failing key falls back too


def test_zoom_route_returns_suggestions_without_a_key():
    from tests.helpers import client

    pid = client.post("/projects", json={"name": "zoom"}).json()["id"]
    r = client.post(f"/projects/{pid}/suggest-zooms", json={"scenes": [{"target": "Save", "action": "click", "narration": ""}]})
    assert r.status_code == 200 and r.json()["source"] == "rules" and r.json()["zooms"][0]["zoom"] is True


def test_zooms_are_batched_and_a_slow_batch_falls_back(monkeypatch):
    """162 scenes in one call took >60s behind the proxy (504). Batches run in
    parallel; the one that misses the deadline gets rules for just its scenes."""
    import json as _json
    import time

    from app import rewrite

    scenes = [{"target": "Save", "action": "click", "narration": ""} for _ in range(100)]

    def fake(system, prompt, **kw):
        listed = _json.loads(prompt.split("Scenes:\n", 1)[1])
        if len(listed) == 20:  # the last batch (80..99) is too slow
            time.sleep(1.0)
        return _json.dumps([{"i": 0, "scale": 1.6}])  # only the first scene of each batch

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "provider_name", lambda: "openrouter")
    monkeypatch.setattr(rewrite, "complete", fake)
    monkeypatch.setattr(rewrite, "AI_DEADLINE_S", 0.3)
    t0 = time.monotonic()
    zooms, source = rewrite.suggest_zooms_with_source(scenes)
    assert time.monotonic() - t0 < 0.9  # never waits for the slow batch
    assert len(zooms) == 100 and source == "mixed"
    assert zooms[0] == {"zoom": True, "scale": 1.6} and zooms[1]["zoom"] is False
    assert zooms[40]["zoom"] is True and zooms[41]["zoom"] is False
    assert all(z["zoom"] for z in zooms[80:])  # rules: every click zooms


def test_script_and_rewrite_batches_keep_existing_text_on_failure(monkeypatch):
    from app import rewrite

    calls = []

    def fake(system, prompt, **kw):
        calls.append(prompt)
        if len(calls) == 2:
            raise RuntimeError("upstream 502")
        return "[]"

    lines = [f"line {i}" for i in range(45)]
    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "_parse", lambda text, n: [f"new {k}" for k in range(n)])
    monkeypatch.setattr(rewrite, "complete", fake)
    out = rewrite.rewrite_lines(lines)
    assert len(out) == 45 and len(calls) == 2
    changed = [o.startswith("new") for o in out]
    assert changed.count(True) in (30, 15) and changed.count(False) in (15, 30)
    assert all(o == lines[i] for i, o in enumerate(out) if not o.startswith("new"))

    scenes = [{"target": "x", "narration": f"old {i}", "seconds": 3} for i in range(45)]
    calls.clear()
    got = rewrite.generate_script(scenes)
    assert len(got) == 45
    assert all(g == f"old {i}" for i, g in enumerate(got) if not g.startswith("new"))
