"""The narration script a user supplies for a recording without a voiceover:
stored with the session, replaceable later (which re-runs understanding), and
the pause-marker helpers both API and worker rely on."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db import SessionLocal
from app.editspec import detect_filler, effective_script, spoken_text, split_pauses, tokenize
from app.models import Job
from app.routers import sessions as sessions_router
from tests.helpers import client, other_client


def _session(script: str | None = None) -> str:
    pid = client.post("/projects", json={"name": "scripted"}).json()["id"]
    body = {"project_id": pid, "source_type": "upload"}
    if script is not None:
        body["script"] = script
    return client.post("/sessions", json=body).json()["id"]


def test_script_is_stored_at_create_and_returned_in_detail():
    sid = _session("  Open the dashboard. Then export.  ")
    assert client.get(f"/sessions/{sid}").json()["script"] == "Open the dashboard. Then export."
    assert client.get(f"/sessions/{_session()}").json()["script"] is None
    assert client.get(f"/sessions/{_session('   ')}").json()["script"] is None


def test_set_script_saves_and_reprocesses(monkeypatch):
    calls = []
    monkeypatch.setattr(sessions_router, "enqueue_understanding", lambda sid: calls.append(sid))
    sid = _session()
    assert client.put(f"/sessions/{sid}/script", json={"script": "A new script."}).status_code == 200
    assert client.get(f"/sessions/{sid}").json()["script"] == "A new script."
    # an empty script clears it (back to transcription) and reprocesses too
    assert client.put(f"/sessions/{sid}/script", json={"script": ""}).status_code == 200
    assert client.get(f"/sessions/{sid}").json()["script"] is None
    assert calls == [sid, sid]


def test_set_script_refused_while_processing(monkeypatch):
    calls = []
    monkeypatch.setattr(sessions_router, "enqueue_understanding", lambda sid: calls.append(sid))
    sid = _session("Original script.")
    db = SessionLocal()
    db.add(Job(session_id=sid, stage="media", version=1, status="running", attempts=1,
               started_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    assert client.put(f"/sessions/{sid}/script", json={"script": "Changed."}).status_code == 409
    assert client.get(f"/sessions/{sid}").json()["script"] == "Original script." and calls == []


def test_set_script_on_another_users_session_is_404(monkeypatch):
    monkeypatch.setattr(sessions_router, "enqueue_understanding", lambda sid: None)
    sid = _session()
    assert other_client.put(f"/sessions/{sid}/script", json={"script": "Mine now."}).status_code == 404


def test_oversized_script_is_rejected():
    pid = client.post("/projects", json={"name": "big"}).json()["id"]
    r = client.post("/sessions", json={"project_id": pid, "source_type": "upload", "script": "x" * 50_001})
    assert r.status_code == 422


# ---- pause markers ----------------------------------------------------------
def test_split_pauses_alternates_text_and_clamped_seconds():
    assert split_pauses("Open the menu. [pause:1.5] Then export.") == ["Open the menu.", 1.5, "Then export."]
    assert split_pauses("[pause:0.01] Hi [PAUSE:9]") == [0.2, "Hi", 3.0]
    assert split_pauses("No markers here.") == ["No markers here."]
    assert split_pauses("") == []


def test_spoken_text_strips_markers():
    assert spoken_text("Open the menu. [pause:1.5] Then export.") == "Open the menu. Then export."
    assert spoken_text("[pause:1]") == ""


def test_pause_marker_is_one_token_and_never_a_filler():
    words = tokenize("So open it [pause:1] like this")
    assert "[pause:1]" in words
    removed = detect_filler(words)
    assert words.index("[pause:1]") not in removed
    assert effective_script(words, removed) == "open it [pause:1] this"
