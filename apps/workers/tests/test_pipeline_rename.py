"""A name the user typed survives a (re)process: the auto-title is not even asked."""

from __future__ import annotations

import app.titles as titles
from app.db import SessionLocal
from app.models import CaptureSession, Event, Project
from worker.pipeline.run import run_pipeline

PLACEHOLDER = "Screen Recording · 4 Sept, 09:54"


def _run(name: str, locked: int, monkeypatch) -> tuple[str, list[int]]:
    calls: list[int] = []

    def fake_suggest(transcript, steps=None):
        calls.append(1)
        return "AI picked this", "llm"

    monkeypatch.setattr(titles, "suggest_title", fake_suggest)
    db = SessionLocal()
    try:
        p = Project(name=name, name_locked=locked)
        db.add(p)
        db.commit()
        sess = CaptureSession(
            project_id=p.id, source_type="extension", telemetry="present", status="captured",
            duration_ms=4000,
        )
        db.add(sess)
        db.commit()
        for i, t in enumerate([1000, 3000]):
            db.add(Event(session_id=sess.id, seq=i, type="click", t_ms=t, selector=f"#b{i}",
                         text=f"Button {i}", bbox_json=[i, i, 8, 8]))
        db.commit()
        run_pipeline(sess.id)
        db.expire_all()
        return db.get(Project, p.id).name, calls
    finally:
        db.close()


def test_unlocked_placeholder_name_is_replaced_by_auto_title(monkeypatch):
    name, calls = _run(PLACEHOLDER, 0, monkeypatch)
    assert name == "AI picked this" and calls == [1]


def test_locked_name_is_kept_and_no_title_call_is_made(monkeypatch):
    name, calls = _run(PLACEHOLDER, 1, monkeypatch)
    assert name == PLACEHOLDER and calls == []
