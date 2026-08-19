from tests.helpers import client


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_read_project():
    r = client.post("/projects", json={"name": "My first flow"})
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["name"] == "My first flow"
    pid = project["id"]

    r = client.get(f"/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid

    r = client.get("/projects")
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())


def test_get_missing_project_404():
    assert client.get("/projects/does-not-exist").status_code == 404
