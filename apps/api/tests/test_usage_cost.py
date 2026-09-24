"""Admin AI-cost endpoint: total OpenRouter spend for a date range."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.routers.admin import _cost_query, _totals_for_key
from tests.helpers import client as user_client, make_client

admin_client = make_client("admin@example.com", name="Admin")

ROWS = [
    {"api_key_id": "recease", "total_usage": 1.25, "request_count": "10", "tokens_total": "500"},
    {"api_key_id": "other-app", "total_usage": 40.0, "request_count": "99", "tokens_total": "9999"},
]


@pytest.fixture
def management_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_management_key", "mgmt-key")
    monkeypatch.setattr(get_settings(), "openrouter_cost_key", "recease")


def test_totals_for_key_picks_only_the_named_key():
    assert _totals_for_key(ROWS, "recease") == {"cost_usd": 1.25, "request_count": 10, "tokens_total": 500}


def test_totals_for_key_sums_everything_when_unset():
    assert _totals_for_key(ROWS, "") == {"cost_usd": 41.25, "request_count": 109, "tokens_total": 10499}


def test_totals_for_key_zero_when_key_has_no_row():
    assert _totals_for_key(ROWS, "unused-key") == {"cost_usd": 0, "request_count": 0, "tokens_total": 0}


def test_cost_query_converts_ist_days_to_utc_instants():
    body = _cost_query(date(2026, 9, 1), date(2026, 9, 21))
    assert body["metrics"] == ["total_usage", "request_count", "tokens_total"]
    assert body["dimensions"] == ["api_key_id"]
    # IST midnight on the 1st is 18:30 UTC the day before; the end is the
    # midnight AFTER the inclusive `to` day.
    assert body["time_range"] == {"start": "2026-08-31T18:30:00Z", "end": "2026-09-21T18:30:00Z"}


def test_cost_query_no_range_is_last_six_months():
    body = _cost_query(None, None)
    start = datetime.strptime(body["time_range"]["start"], "%Y-%m-%dT%H:%M:%SZ")
    end = datetime.strptime(body["time_range"]["end"], "%Y-%m-%dT%H:%M:%SZ")
    assert end - start == timedelta(days=183)
    assert abs(end - datetime.now(timezone.utc).replace(tzinfo=None)) < timedelta(minutes=1)


def test_usage_cost_returns_openrouter_totals(management_key):
    with patch(
        "app.routers.admin.fetch_openrouter_cost",
        return_value={"cost_usd": 12.5, "request_count": 40, "tokens_total": 9000},
    ) as fetch:
        r = admin_client.get("/admin/usage/cost?from=2026-09-01&to=2026-09-21")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cost_usd"] == 12.5
    assert body["request_count"] == 40
    assert body["tokens_total"] == 9000
    assert body["from_date"] == "2026-09-01"
    fetch.assert_called_once_with("mgmt-key", date(2026, 9, 1), date(2026, 9, 21), key_name="recease")


def test_usage_cost_404_when_not_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_management_key", "")
    assert admin_client.get("/admin/usage/cost").status_code == 404


def test_usage_cost_502_when_openrouter_fails(management_key):
    with patch("app.routers.admin.fetch_openrouter_cost", side_effect=RuntimeError("boom")):
        r = admin_client.get("/admin/usage/cost")
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]


def test_usage_cost_requires_admin(management_key):
    assert user_client.get("/admin/usage/cost").status_code == 403
