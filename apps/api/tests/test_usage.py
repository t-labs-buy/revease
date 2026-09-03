"""Usage tracking: counts of videos generated and screens recorded, the admin
summary endpoint, and the key-protected external report endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import UsageEvent
from app.usage import record_event
from tests.helpers import anon, client as user_client, make_client

admin_client = make_client("admin@example.com", name="Admin")


def _reset_events():
    db = SessionLocal()
    try:
        db.execute(delete(UsageEvent))
        db.commit()
    finally:
        db.close()


def test_record_event_counts():
    _reset_events()
    record_event("video", duration_ms=60_000)
    record_event("video", duration_ms=30_000)
    record_event("recording", duration_ms=5_000)
    record_event("bogus")  # unknown kinds are dropped, not raised

    body = admin_client.get("/admin/usage").json()
    assert body["videos_generated"] == 2
    assert body["screens_recorded"] == 1
    assert body["video_duration_ms"] == 90_000
    assert body["recording_duration_ms"] == 5_000


def test_usage_date_filter():
    _reset_events()
    record_event("video")
    db = SessionLocal()
    try:
        db.add(UsageEvent(kind="video", created_at=datetime.now(IST).replace(tzinfo=None) - timedelta(days=10)))
        db.commit()
    finally:
        db.close()

    today = datetime.now(IST).date()  # date filters are IST calendar days
    body = admin_client.get(f"/admin/usage?from={today.isoformat()}&to={today.isoformat()}").json()
    assert body["videos_generated"] == 1  # the old event is outside the range
    assert admin_client.get("/admin/usage").json()["videos_generated"] == 2  # no range = all time


def test_usage_requires_admin():
    assert user_client.get("/admin/usage").status_code == 403
    assert anon.get("/admin/usage").status_code == 401


def test_report_endpoint_key_auth():
    _reset_events()
    record_event("recording")

    # no key / wrong key rejected; login token is irrelevant here
    assert anon.get("/admin/usage/report").status_code == 401
    assert anon.get("/admin/usage/report", headers={"X-Report-Key": "nope"}).status_code == 401

    r = anon.get("/admin/usage/report", headers={"X-Report-Key": "test-report-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["screens_recorded"] == 1
    # the report carries the per-event detail too
    assert body["events_total"] == 1
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "recording"

    # pagination: offset past the end returns an empty page, totals unaffected
    record_event("video")
    page2 = anon.get(
        "/admin/usage/report?limit=1&offset=1", headers={"X-Report-Key": "test-report-key"}
    ).json()
    assert page2["events_total"] == 2
    assert len(page2["events"]) == 1
    assert page2["screens_recorded"] == 1  # summary still covers the whole range
    empty = anon.get(
        "/admin/usage/report?limit=1&offset=5", headers={"X-Report-Key": "test-report-key"}
    ).json()
    assert empty["events"] == []


def test_completing_a_capture_records_usage():
    _reset_events()
    project = user_client.post("/projects", json={"name": "usage-capture-proj"}).json()
    sess = user_client.post(
        "/sessions", json={"project_id": project["id"], "source_type": "recorder"}
    ).json()

    r = user_client.post(f"/sessions/{sess['id']}/complete", json={"duration_ms": 1000})
    assert r.status_code == 200
    # completing the same session again must not double-count
    user_client.post(f"/sessions/{sess['id']}/complete", json={"duration_ms": 1000})

    # an uploaded video goes through the same endpoint but counts separately
    up = user_client.post(
        "/sessions", json={"project_id": project["id"], "source_type": "upload"}
    ).json()
    user_client.post(f"/sessions/{up['id']}/complete", json={"duration_ms": 2000})

    body = admin_client.get("/admin/usage").json()
    assert body["screens_recorded"] == 1
    assert body["videos_uploaded"] == 1
    assert body["upload_duration_ms"] == 2000

    # the events carry who did it and which kind it was
    events = admin_client.get("/admin/usage/events").json()["events"]
    assert [e["kind"] for e in events] == ["upload", "recording"]  # newest first
    assert events[1]["user_email"] == "owner@example.com"
    assert events[1]["duration_ms"] == 1000  # from the complete payload


def test_usage_events_listing():
    _reset_events()
    record_event("video", user_id=None)  # pre-attribution rows have no user
    record_event("recording", user_id=admin_client.get("/auth/me").json()["id"])

    body = admin_client.get("/admin/usage/events").json()
    assert body["total"] == 2
    events = body["events"]
    assert [e["kind"] for e in events] == ["recording", "video"]  # newest first
    assert events[0]["user_email"] == "admin@example.com"
    assert events[1]["user_email"] is None

    assert user_client.get("/admin/usage/events").status_code == 403

    today = datetime.now(IST).date().isoformat()
    filtered = admin_client.get(f"/admin/usage/events?from={today}&to={today}").json()
    assert filtered["total"] == 2

    # pagination: one event per page, offset walks the list, total stays put
    page2 = admin_client.get("/admin/usage/events?limit=1&offset=1").json()
    assert page2["total"] == 2
    assert len(page2["events"]) == 1
    assert page2["events"][0]["kind"] == "video"

    # timestamps come back as IST wall-clock time (no zone marker)
    returned = datetime.fromisoformat(filtered["events"][0]["created_at"])
    assert returned.tzinfo is None
    assert abs(returned - datetime.now(IST).replace(tzinfo=None)) < timedelta(minutes=5)
