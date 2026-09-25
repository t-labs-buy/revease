"""Project titles: stated goal > dominant topic > touched screens > keep the name.
Offline (conftest has no LLM keys); the LLM path is exercised with a fake client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import titles
from app.titles import heuristic_title, project_title


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("So today I'm going to show you how to create an API key in the settings page. First we go to Settings.",
         "Create an API Key in the Settings"),
        ("Um okay so hi everyone, in this video we will walk through configuring the SAP CPI integration flow.",
         "Configuring the SAP CPI Integration Flow"),
        ("Let's see how we can set up two-factor authentication for your account. Click on profile.",
         "Set Up Two-Factor Authentication for Your Account"),
        ("In this demo I will explain the approval workflow for purchase orders in Oracle.",
         "Approval Workflow for Purchase Orders in Oracle"),
        ("Hey guys. We want to migrate the customer data from Salesforce to HubSpot, so first export.",
         "Migrate the Customer Data from Salesforce to HubSpot"),
    ],
)
def test_stated_goal_becomes_the_title(transcript, expected):
    assert heuristic_title(transcript) == expected


def test_dominant_topic_when_no_goal_is_stated():
    t = ("Alright. Here I open the dashboard. Then the payment gateway settings. The payment gateway "
         "needs the merchant ID. We paste the merchant ID into the payment gateway form and save.")
    assert heuristic_title(t) == "Payment Gateway"


def test_never_the_first_words_of_rambling_speech():
    assert heuristic_title("okay so this is the thing and then we do this and that and it works") == ""
    assert project_title("") == ""


def test_steps_name_a_silent_recording():
    steps = [{"screen_name": "Billing Settings", "target": "Save", "action": "click"}] * 3
    assert heuristic_title("", steps) == "Billing Settings Walkthrough"
    repeated = [{"screen_name": "Screen 1", "target": "Invoices tab", "action": "click"}] * 2 + [
        {"screen_name": "", "target": "Silence — add narration", "action": "custom"}]
    assert heuristic_title("", repeated) == "Invoices Tab Walkthrough"
    # one stray click on a generic screen is not enough to name a recording
    once = [{"screen_name": "Screen 1", "target": "Invoices tab", "action": "click"}]
    assert heuristic_title("", once) == ""


def test_placeholder_names_only():
    from app.titles import is_placeholder_name

    assert is_placeholder_name("Screen Recording · 4 Sept, 09:54")
    assert is_placeholder_name("Screen Recording 2026-09-24 at 3.16 PM")
    assert not is_placeholder_name("Recording a Product Demo Tab")
    assert not is_placeholder_name("Map Coverage Tab Overview")


def test_llm_title_is_used_and_sanitised(monkeypatch):
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen["prompt"] = kw["messages"][0]["content"]
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='Title: "Create an API Key."\n')])

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(
        anthropic_api_key="k", anthropic_model="m", openrouter_api_key="", openrouter_model="o"))
    steps = [{"action": "click", "target": "API Keys", "screen_name": "Settings"}]
    assert project_title("so today we make a key", steps) == "Create an API Key"
    assert "- click API Keys (on Settings)" in seen["prompt"]


def test_llm_failure_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr(titles, "llm_title", lambda t, s: "")
    assert project_title("I will show you how to export invoices to Excel.") == "Export Invoices to Excel"
