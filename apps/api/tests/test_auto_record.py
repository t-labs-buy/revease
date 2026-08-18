"""Auto Record router — the Claude call is mocked so the loop/idempotency/plan
logic is tested deterministically without a key or network."""

import app.routers.auto_record as ar

from tests.helpers import client


def _project() -> str:
    return client.post("/projects", json={"name": "auto test"}).json()["id"]


def _obs(idx=0):
    return {
        "expected_index": idx,
        "observation": {
            "url": "https://app.example.com",
            "title": "Example",
            "elements": [{"ref": "e1", "tag": "button", "text": "Save", "selector": "#save"}],
            "screenshot_b64": None,
        },
        "results": [],
    }


def test_create_run_parses_plan_into_items():
    pid = _project()
    r = client.post("/auto-record/runs", json={
        "project_id": pid,
        "coverage_plan": "- Open the dashboard\n- Create an invoice\n- Save it",
        "transcript": "Here is the demo.",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "created"
    assert [it["text"] for it in body["plan"]] == [
        "Open the dashboard", "Create an invoice", "Save it",
    ]
    assert all(it["status"] == "pending" for it in body["plan"])


def test_step_loop_and_idempotent_replay(monkeypatch):
    pid = _project()
    run = client.post("/auto-record/runs", json={
        "project_id": pid, "coverage_plan": "Do the thing", "transcript": "",
    }).json()
    run_id = run["run_id"]

    calls = {"n": 0}

    def fake_decide(**kwargs):
        calls["n"] += 1
        return {
            "action": "click", "ref": "e1", "target": "Save button",
            "intent": "Save the record", "screen_name": "Editor",
            "plan_item_id": "p1", "plan_item_completed": True,
            "progress_note": "Clicking Save",
        }

    monkeypatch.setattr(ar, "decide_next_action", fake_decide)

    # First decision at index 0.
    r = client.post(f"/auto-record/runs/{run_id}/step", json=_obs(0))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"]["action"] == "click" and body["action"]["index"] == 0
    assert body["step_count"] == 1
    # plan item marked done by the server
    assert body["plan"][0]["status"] == "done"

    # Replaying index 0 must NOT call the model again (idempotent).
    r2 = client.post(f"/auto-record/runs/{run_id}/step", json=_obs(0))
    assert r2.status_code == 200 and r2.json()["action"]["index"] == 0
    assert calls["n"] == 1  # model called once, not twice

    # A stale/mismatched index is a conflict.
    r3 = client.post(f"/auto-record/runs/{run_id}/step", json=_obs(5))
    assert r3.status_code == 409


def test_step_cap_forces_done(monkeypatch):
    pid = _project()
    run = client.post("/auto-record/runs", json={
        "project_id": pid, "coverage_plan": "x", "transcript": "", "max_steps": 1,
    }).json()
    run_id = run["run_id"]
    monkeypatch.setattr(ar, "decide_next_action", lambda **k: {
        "action": "click", "ref": "e1", "progress_note": "go", "plan_item_id": "p1",
    })
    # step 0 consumes the only allowed decision
    client.post(f"/auto-record/runs/{run_id}/step", json=_obs(0))
    # step 1 hits the cap -> forced done
    r = client.post(f"/auto-record/runs/{run_id}/step", json=_obs(1))
    assert r.json()["done"] is True


def test_complete_enqueues_and_marks_captured(monkeypatch):
    # Don't hit a real broker.
    monkeypatch.setattr(ar, "enqueue_understanding", lambda sid: None)
    pid = _project()
    run = client.post("/auto-record/runs", json={
        "project_id": pid, "coverage_plan": "x", "transcript": "hi",
    }).json()
    # add one telemetry event so telemetry flips to present
    client.post(f"/sessions/{run['session_id']}/events",
                json={"events": [{"seq": 0, "type": "click", "t_ms": 100}]})
    r = client.post(f"/auto-record/runs/{run['run_id']}/complete",
                    json={"status": "completed", "duration_ms": 4200})
    assert r.status_code == 200 and r.json()["status"] == "capture_done"
    sess = client.get(f"/sessions/{run['session_id']}").json()
    assert sess["status"] == "captured" and sess["telemetry"] == "present"


def test_abort_marks_run_aborted():
    pid = _project()
    run = client.post("/auto-record/runs", json={
        "project_id": pid, "coverage_plan": "x", "transcript": "",
    }).json()
    r = client.post(f"/auto-record/runs/{run['run_id']}/abort")
    assert r.status_code == 200 and r.json()["status"] == "aborted"
