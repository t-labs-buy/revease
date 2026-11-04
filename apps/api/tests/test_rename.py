"""Renaming a project: who may, what it touches, and that auto-title respects it."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Project, VideoProject, WorkflowGraphRow
from tests.helpers import anon, client, other_client


def _project(name: str = "Screen Recording · 4 Sept, 09:54") -> str:
    return client.post("/projects", json={"name": name}).json()["id"]


def _video(pid: str, title: str) -> None:
    with SessionLocal() as db:
        db.add(WorkflowGraphRow(project_id=pid, version=1,
                                graph_json={"version": 1, "title": "t", "steps": []}))
        db.add(VideoProject(project_id=pid, graph_version=1,
                            edit_spec_json={"title": title, "segments": []}))
        db.commit()


def _save_title(pid: str, title: str, **extra):
    return client.patch(f"/projects/{pid}/video",
                        json={"edit_spec": {"segments": [], "title": title, **extra}})


def _spec_title(pid: str) -> str:
    with SessionLocal() as db:
        vp = db.query(VideoProject).filter_by(project_id=pid).one()
        return vp.edit_spec_json["title"]


def test_owner_renames_and_name_is_trimmed_and_locked():
    pid = _project()
    r = client.patch(f"/projects/{pid}", json={"name": "  Onboarding \n tour  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Onboarding tour"
    assert client.get(f"/projects/{pid}").json()["name"] == "Onboarding tour"
    with SessionLocal() as db:
        assert db.get(Project, pid).name_locked == 1


def test_blank_or_too_long_names_are_rejected():
    pid = _project("Keep me")
    assert client.patch(f"/projects/{pid}", json={"name": "   "}).status_code == 422
    assert client.patch(f"/projects/{pid}", json={"name": ""}).status_code == 422
    assert client.patch(f"/projects/{pid}", json={"name": "x" * 201}).status_code == 422
    assert client.get(f"/projects/{pid}").json()["name"] == "Keep me"


def test_strangers_get_404_and_anonymous_401():
    pid = _project("Private")
    assert other_client.patch(f"/projects/{pid}", json={"name": "Hijack"}).status_code == 404
    assert anon.patch(f"/projects/{pid}", json={"name": "Hijack"}).status_code == 401
    assert client.get(f"/projects/{pid}").json()["name"] == "Private"


def test_collaborator_may_rename():
    pid = _project("Shared")
    client.post(f"/projects/{pid}/collaborators", json={"email": "other@example.com"})
    assert other_client.patch(f"/projects/{pid}", json={"name": "Renamed by collab"}).status_code == 200


def test_renaming_the_project_sets_the_video_title():
    pid = _project("Old name")
    _video(pid, "Some other title")
    client.patch(f"/projects/{pid}", json={"name": "New name"})
    assert _spec_title(pid) == "New name"


def test_editing_the_video_title_renames_and_locks_the_project():
    pid = _project("Old name")
    _video(pid, "Old name")
    r = _save_title(pid, "  Typed in   editor ")
    assert r.status_code == 200, r.text
    assert client.get(f"/projects/{pid}").json()["name"] == "Typed in editor"
    with SessionLocal() as db:
        assert db.get(Project, pid).name_locked == 1


def test_saving_other_edits_or_a_blank_title_leaves_the_name_alone():
    pid = _project("Keep this")
    _video(pid, "Keep this")
    assert _save_title(pid, "Keep this", pace=1.25).status_code == 200
    assert _save_title(pid, "   ").status_code == 200
    assert client.get(f"/projects/{pid}").json()["name"] == "Keep this"
    with SessionLocal() as db:
        assert db.get(Project, pid).name_locked == 0


def test_stranger_cannot_rename_through_the_video_title():
    pid = _project("Mine")
    _video(pid, "Mine")
    r = other_client.patch(f"/projects/{pid}/video",
                           json={"edit_spec": {"segments": [], "title": "Hijack"}})
    assert r.status_code == 404
    assert client.get(f"/projects/{pid}").json()["name"] == "Mine"
