"""The whole-recording Generate (app.videoscript + its route): frames are
windowed and every one is sent once, the model's reply is read in whatever
shape it comes, lines are joined into one timed script Apply script can place,
"fit" mode budgets each line by the footage to the next, and the route queues
a Job the status endpoint lists. Also the tolerant parser the per-scene
Generate now shares, with the honest error that replaced the bogus timeout."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app import rewrite
from app import videoscript as vs
from app.db import SessionLocal
from app.models import Job, MediaAsset
from app.routers import sessions as sessions_router
from app.videoscript import (
    TimedLine,
    fit_lines,
    join_lines,
    parse_timed,
    plan_windows,
    timed_script_text,
    window_bounds,
)
from tests.helpers import client, other_client


# ---- pure helpers ------------------------------------------------------------
def test_plan_windows_sends_every_frame_once_in_near_equal_parts():
    kf = [(float(t), f"f{t}") for t in range(130)]
    wins = plan_windows(kf, per_call=60)
    assert [len(w) for w in wins] == [44, 44, 42]
    assert [k for w in wins for k in w] == kf
    assert plan_windows(kf[:60], per_call=60) == [kf[:60]]
    assert plan_windows([]) == []
    assert window_bounds(wins, 130.0) == [(0.0, 44.0), (44.0, 88.0), (88.0, 130.0)]


def test_parse_timed_tolerates_the_shapes_models_answer_in():
    one = '[{"t": 0, "line": "Hi."}, {"t": "0:03.5", "text": "Click Next."}]'
    assert parse_timed(one) == [TimedLine(0.0, "Hi."), TimedLine(3.5, "Click Next.")]
    split = '```json\n[{"t":0,"line":"A"}]\n[{"t":2,"line":"B"}]\n```'
    assert [ln.text for ln in parse_timed(split)] == ["A", "B"]
    prose = 'Here you go: [{"time": 4, "narration": " two  words "}]'
    assert parse_timed(prose) == [TimedLine(4.0, "two words")]
    assert parse_timed('[{"t": 1, "line": ""}, "junk", 3]') == []
    assert parse_timed("no json at all") == []
    undated = parse_timed('{"line": "no time"}')
    assert len(undated) == 1 and undated[0].t != undated[0].t  # NaN: join_lines places it


def test_join_lines_orders_clamps_and_fills_missing_times():
    parts = [
        [TimedLine(2.0, "hook"), TimedLine(1.0, "dated before the previous")],
        [TimedLine(float("nan"), "undated"), TimedLine(99.0, "past the end")],
    ]
    out = join_lines(parts, 30.0)
    assert [ln.text for ln in out] == ["hook", "dated before the previous", "undated", "past the end"]
    assert [ln.t for ln in out] == [0.0, 2.5, 3.0, 30.0]
    assert join_lines([], 10.0) == []


def test_kept_ranges_reads_the_editor_trim_out_of_the_spec():
    from app.videoscript import kept_ranges

    seg = lambda a, b, **kw: {"source_start_ms": a, "source_end_ms": b, **kw}  # noqa: E731
    whole = {"segments": [seg(0, 5000), seg(5000, 20000), seg(20000, 34990)]}
    assert kept_ranges(whole, 35067) is None  # a few ms short of the end is no trim
    assert kept_ranges(None, 35067) is None and kept_ranges({"segments": []}, 35067) is None
    # a skipped scene and a shortened one: two kept stretches, touching scenes joined
    trimmed = {"segments": [seg(0, 5000), seg(5000, 12000, skipped=True), seg(12000, 20000), seg(22000, 35067)]}
    assert kept_ranges(trimmed, 35067) == [[0, 5000], [12000, 20000], [22000, 35067]]
    # the spec-level trim window cuts everything to [start, end]
    boxed = {"segments": [seg(0, 20000), seg(20000, 35067)],
             "trim": {"enabled": True, "start_ms": 3000, "end_ms": 30000}}
    assert kept_ranges(boxed, 35067) == [[3000, 30000]]
    # only the head cut: one range, but not from 0 — still a trim
    assert kept_ranges({"segments": [seg(4000, 35067)]}, 35067) == [[4000, 35067]]


def test_timed_script_text_is_what_apply_script_reads():
    lines = [TimedLine(0.0, "Open Integrations."), TimedLine(63.4, "Click Next."), TimedLine(3725.0, "Done.")]
    assert timed_script_text(lines) == "[0:00.0] Open Integrations.\n[1:03.4] Click Next.\n[1:02:05.0] Done."
    assert timed_script_text([TimedLine(1.0, "  ")]) == ""
    # a line closed at a cut is written with an end time, which scriptalign honours
    assert timed_script_text([TimedLine(0.0, "Open it.", 20.0)]) == "[0:00.0 - 0:20.0] Open it."


def test_align_to_ranges_keeps_scenes_out_of_removed_footage():
    from app.videoscript import align_to_ranges

    spans = [(0.0, 20.0), (30.0, 40.0)]
    # dated just after the cut: moved onto the edge where footage resumes
    out = align_to_ranges([TimedLine(0.0, "a"), TimedLine(31.0, "b")], spans)
    assert [(ln.t, ln.t_end) for ln in out] == [(0.0, None), (30.0, None)]
    # dated inside the cut: same
    out = align_to_ranges([TimedLine(0.0, "a"), TimedLine(25.0, "b")], spans)
    assert [(ln.t, ln.t_end) for ln in out] == [(0.0, None), (30.0, None)]
    # far after the cut: the line before closes at the cut, the rest is a blank scene
    out = align_to_ranges([TimedLine(0.0, "a"), TimedLine(36.0, "b")], spans)
    assert [(ln.t, ln.t_end) for ln in out] == [(0.0, 20.0), (36.0, None)]
    # nothing to do without a gap
    one = [TimedLine(0.0, "a"), TimedLine(5.0, "b")]
    assert align_to_ranges(one, [(0.0, 40.0)]) == one


def test_fit_lines_budgets_each_line_by_the_gap_to_the_next(monkeypatch):
    seen: list[str] = []

    def fake_complete(system, prompt, **kw):
        seen.append(prompt)
        return json.dumps(["Click Create."])

    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", fake_complete)
    lines = [
        TimedLine(0.0, "Short hook."),
        TimedLine(3.0, "This line is far too long for the two seconds it has on screen here."),
        TimedLine(5.0, "Then the suite is ready to run."),
    ]
    out = fit_lines(lines, 20.0)
    assert [ln.t for ln in out] == [0.0, 3.0, 5.0]
    assert out[0].text == "Short hook." and out[2].text == "Then the suite is ready to run."
    assert out[1].text == "Click Create."
    # only the overrun went back, with the budget of its 2 s gap
    assert json.loads(seen[0].split("\n")[3]) == [rewrite.scene_word_budget(2.0)]
    assert fit_lines([], 20.0) == []


def test_write_window_shows_frames_prior_lines_and_retries_once(monkeypatch):
    calls: list[list] = []

    def fake_vision(system, parts, **kw):
        calls.append(parts)
        assert system is vs.VIDEO_SYSTEM
        return "Sorry, I cannot." if len(calls) == 1 else '[{"t": 44, "line": "Choose the adapter."}]'

    monkeypatch.setattr(vs, "complete_vision", fake_vision)
    out = vs.write_window(
        [(44.0, b"jpg"), (45.0, b"jpg2")], t0=44.0, t1=88.0, duration_s=130.0, index=1, count=3,
        title="TestEase", brief="A demo", mode="free", prior=[TimedLine(0.0, "Meet TestEase.")],
    )
    assert out == [TimedLine(44.0, "Choose the adapter.")]
    head = calls[0][0]
    assert head.startswith('Video title: "TestEase"') and "part 2 of 3" in head and "Meet TestEase." in head
    assert vs.mode_note("free", 44.0) in head and "Timing:" not in head
    # the pace is stated as words and lines for this part, not left to the model
    assert "about 132 words" in head and "never more than 176" in head and "roughly 15 lines" in head
    fit = vs.window_parts([], t0=0.0, t1=35.0, duration_s=35.0, index=0, count=1,
                          title="t", brief="b", mode="fit", prior=[])[0]
    assert "at most 80 words" in fit and "roughly 12 lines" in fit
    assert calls[0][1:5] == ["t=44.0s", b"jpg", "t=45.0s", b"jpg2"]
    # the brief sits both before the frames and right next to the ask
    assert "A demo" in calls[0][0] and calls[0][-1].startswith("Author's brief") and "A demo" in calls[0][-1]
    assert calls[1][-1].startswith("Your previous answer")


def test_write_window_gives_up_after_two_unusable_replies(monkeypatch):
    monkeypatch.setattr(vs, "complete_vision", lambda *a, **k: "nothing useful")
    with pytest.raises(ValueError, match="could not be read"):
        vs.write_window([(0.0, b"jpg")], t0=0.0, t1=10.0, duration_s=10.0, index=0, count=1,
                        title="t", brief="b", mode="fit", prior=[])


# ---- the per-scene parser, now tolerant -------------------------------------
def test_parse_accepts_one_array_per_line_and_prose_around():
    assert rewrite._parse('["A"]\n["B"]\n["C"]', 3) == ["A", "B", "C"]
    assert rewrite._parse('Here:\n```json\n["A", "B"]\n```', 2) == ["A", "B"]
    with pytest.raises(ValueError, match="expected 2 lines, got 1"):
        rewrite._parse('["A"]', 2)


def test_generate_script_reports_the_real_reason_not_a_timeout(monkeypatch):
    monkeypatch.setattr(rewrite, "has_llm", lambda: True)
    monkeypatch.setattr(rewrite, "complete", lambda *a, **k: "not json at all")
    with pytest.raises(RuntimeError, match="could not be used"):
        rewrite.generate_script([{"target": "t", "action": "click", "narration": ""}])


# ---- the route ---------------------------------------------------------------
def _session_with_frames(n: int = 3) -> str:
    pid = client.post("/projects", json={"name": "vs"}).json()["id"]
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]
    db = SessionLocal()
    for t in range(n):
        db.add(MediaAsset(session_id=sid, kind="frame", storage_key=f"sessions/{sid}/frames/f{t}.jpg",
                          meta_json={"t": float(t)}))
    db.commit()
    db.close()
    return sid


def test_generate_from_recording_queues_a_script_job(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr(sessions_router, "has_llm", lambda: True)
    monkeypatch.setattr(sessions_router, "enqueue_script_generate", lambda *a: sent.append(a))
    sid = _session_with_frames()
    r = client.post(f"/sessions/{sid}/generate-script",
                    json={"brief": "A demo of TestEase", "mode": "free", "instruction": "Casual"})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["stage"] == "script" and job["status"] == "pending"
    assert len(sent) == 1 and sent[0][0] == sid and sent[0][2:] == ("A demo of TestEase", "free", "Casual")
    st = client.get(f"/sessions/{sid}/status").json()
    assert [j["stage"] for j in st["jobs"]] == ["script"]
    # a second request reuses the row rather than piling up; mode defaults to fit
    assert client.post(f"/sessions/{sid}/generate-script", json={"brief": "Again please"}).status_code == 202
    assert sent[1][3] == "fit"
    assert [j["stage"] for j in client.get(f"/sessions/{sid}/status").json()["jobs"]] == ["script"]


def test_generate_from_recording_refusals(monkeypatch):
    monkeypatch.setattr(sessions_router, "enqueue_script_generate", lambda *a: None)
    sid = _session_with_frames()
    monkeypatch.setattr(sessions_router, "has_llm", lambda: False)
    assert client.post(f"/sessions/{sid}/generate-script", json={"brief": "A demo"}).status_code == 400
    monkeypatch.setattr(sessions_router, "has_llm", lambda: True)
    pid = client.post("/projects", json={"name": "bare"}).json()["id"]
    bare = client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]
    assert client.post(f"/sessions/{bare}/generate-script", json={"brief": "A demo"}).status_code == 400
    assert other_client.post(f"/sessions/{sid}/generate-script", json={"brief": "A demo"}).status_code == 404
    assert client.post(f"/sessions/{sid}/generate-script", json={"brief": "A demo", "mode": "huge"}).status_code == 422
    assert client.post(f"/sessions/{sid}/generate-script", json={"brief": ""}).status_code == 422
    db = SessionLocal()
    db.add(Job(session_id=sid, stage="media", version=1, status="running", attempts=1,
               started_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    assert client.post(f"/sessions/{sid}/generate-script", json={"brief": "A demo"}).status_code == 409
