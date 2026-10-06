"""GET /projects/{id}/transcript — Whisper word timings for the editor's
word-level split. Must follow the ownership rule (404 for someone else's
project) and degrade to an empty list rather than erroring when a project has
no capture or no speech."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import CaptureSession, Transcript
from tests.helpers import anon, client, other_client


def _project_with_words(words: list[dict] | None) -> str:
    pid = client.post("/projects", json={"name": "transcript"}).json()["id"]
    with SessionLocal() as db:
        sess = CaptureSession(project_id=pid, source_type="upload")
        db.add(sess)
        db.flush()
        if words is not None:
            db.add(Transcript(session_id=sess.id, words_json=words, text="", provider="whisper"))
        db.commit()
    return pid


def test_transcript_returns_word_timings_on_the_source_clock():
    words = [
        {"w": "Click", "t_start": 1.0, "t_end": 1.3},
        {"w": "settings.", "t_start": 1.4, "t_end": 1.9},
    ]
    pid = _project_with_words(words)
    r = client.get(f"/projects/{pid}/transcript")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "whisper"
    assert [w["w"] for w in body["words"]] == ["Click", "settings."]
    assert body["words"][1]["t_start"] == 1.4


def test_transcript_is_empty_without_a_capture_or_without_speech():
    no_session = client.post("/projects", json={"name": "bare"}).json()["id"]
    assert client.get(f"/projects/{no_session}/transcript").json()["words"] == []

    no_words = _project_with_words(None)
    assert client.get(f"/projects/{no_words}/transcript").json()["words"] == []


def test_transcript_is_private_to_the_owner():
    pid = _project_with_words([{"w": "hi", "t_start": 0.0, "t_end": 0.2}])
    assert other_client.get(f"/projects/{pid}/transcript").status_code == 404
    assert anon.get(f"/projects/{pid}/transcript").status_code == 401
