from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_project() -> str:
    return client.post("/projects", json={"name": "capture test"}).json()["id"]


def test_recorder_session_flow_marks_telemetry_present():
    pid = _make_project()
    r = client.post(
        "/sessions",
        json={"project_id": pid, "source_type": "recorder", "viewport": {"w": 1280, "h": 720}},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["telemetry"] == "absent"

    # Register + upload a fake video asset (presigned-style PUT).
    tgt = client.post(f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "webm"}).json()
    put = client.put(tgt["url"], content=b"\x00\x01\x02fake-webm")
    assert put.status_code == 204

    # Ingest a click log.
    events = {
        "events": [
            {"seq": 0, "type": "click", "t_ms": 1200, "bbox": [812, 240, 0, 0]},
            {"seq": 1, "type": "click", "t_ms": 3400, "bbox": [980, 320, 0, 0]},
        ]
    }
    r = client.post(f"/sessions/{sid}/events", json=events)
    assert r.status_code == 200 and r.json()["ingested"] == 2

    r = client.post(f"/sessions/{sid}/complete", json={"duration_ms": 5000})
    assert r.status_code == 200
    body = r.json()
    assert body["telemetry"] == "present"
    assert body["status"] == "captured"
    assert body["duration_ms"] == 5000

    detail = client.get(f"/sessions/{sid}").json()
    assert detail["event_count"] == 2
    assert any(a["kind"] == "raw_video" for a in detail["assets"])


def test_plain_upload_flagged_telemetry_absent():
    pid = _make_project()
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "upload"}).json()["id"]
    tgt = client.post(f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "mp4"}).json()
    assert client.put(tgt["url"], content=b"fake-mp4").status_code == 204
    r = client.post(f"/sessions/{sid}/complete", json={})
    assert r.json()["telemetry"] == "absent"  # no events -> CV fallback territory in P2


def test_event_validation_rejects_missing_t_ms_and_bad_bbox():
    pid = _make_project()
    sid = client.post("/sessions", json={"project_id": pid, "source_type": "recorder"}).json()["id"]
    # missing t_ms
    r = client.post(f"/sessions/{sid}/events", json={"events": [{"seq": 0, "type": "click"}]})
    assert r.status_code == 422
    # bbox not length 4
    r = client.post(
        f"/sessions/{sid}/events",
        json={"events": [{"seq": 0, "type": "click", "t_ms": 10, "bbox": [1, 2, 3]}]},
    )
    assert r.status_code == 422


def test_create_session_unknown_project_404():
    r = client.post("/sessions", json={"project_id": "nope", "source_type": "recorder"})
    assert r.status_code == 404


def test_list_sessions_by_project():
    pid = _make_project()
    client.post("/sessions", json={"project_id": pid, "source_type": "recorder"})
    r = client.get("/sessions", params={"project_id": pid})
    assert r.status_code == 200 and len(r.json()) >= 1
