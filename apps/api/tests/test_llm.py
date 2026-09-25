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
    monkeypatch.setattr(rewrite, "complete", lambda system, prompt, max_tokens: '["Open the Settings page."]')
    assert rewrite.rewrite_lines(["um so open settings"]) == ["Open the Settings page."]
