"""Share-to-edit: inviting another registered user to edit a project."""

from tests.helpers import anon, client, other_client

OTHER_EMAIL = "other@example.com"


def _project(name: str = "collab") -> str:
    return client.post("/projects", json={"name": name}).json()["id"]


def test_invite_grants_edit_access_and_shows_under_shared_with_me():
    pid = _project()

    # invisible to the other account until invited
    assert other_client.get(f"/projects/{pid}").status_code == 404
    assert other_client.get(f"/projects/{pid}/collaborators").status_code == 404

    r = client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL.upper()})
    assert r.status_code == 201, r.text
    assert [c["email"] for c in r.json()] == [OTHER_EMAIL]
    # idempotent
    assert len(client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL}).json()) == 1

    # invitee can open and edit (favorite is the simplest write that goes through owned_project)
    got = other_client.get(f"/projects/{pid}")
    assert got.status_code == 200
    assert got.json()["shared_with_me"] is True
    assert got.json()["owner_email"] == "owner@example.com"
    assert other_client.post(f"/projects/{pid}/favorite").status_code == 200
    assert other_client.get(f"/projects/{pid}/collaborators").status_code == 200

    # it appears in their project list, marked shared; the owner's copy is not marked
    mine = {p["id"]: p for p in other_client.get("/projects").json()}
    assert mine[pid]["shared_with_me"] is True and mine[pid]["owner_name"] == "Owner"
    owners = {p["id"]: p for p in client.get("/projects").json()}
    assert owners[pid]["shared_with_me"] is False and owners[pid]["owner_email"] is None


def test_collaborator_cannot_delete_invite_or_manage_share_links():
    pid = _project("limits")
    client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL})

    assert other_client.delete(f"/projects/{pid}").status_code == 404
    assert (
        other_client.post(f"/projects/{pid}/collaborators", json={"email": "owner@example.com"}).status_code
        == 404
    )
    assert other_client.post(f"/projects/{pid}/share", json={"kind": "doc"}).status_code == 404
    assert other_client.get(f"/projects/{pid}/shares").status_code == 404
    # project still exists for the owner
    assert client.get(f"/projects/{pid}").status_code == 200


def test_invite_validation():
    pid = _project("validation")
    r = client.post(f"/projects/{pid}/collaborators", json={"email": "nobody@example.com"})
    assert r.status_code == 404 and "no RevEase account" in r.json()["detail"]
    r = client.post(f"/projects/{pid}/collaborators", json={"email": "owner@example.com"})
    assert r.status_code == 400
    assert anon.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL}).status_code == 401


def test_remove_and_leave():
    pid = _project("leave")
    client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL})
    other_id = other_client.get("/auth/me").json()["id"]

    # a collaborator can remove themselves…
    r = other_client.delete(f"/projects/{pid}/collaborators/{other_id}")
    assert r.status_code == 200 and r.json() == []
    assert other_client.get(f"/projects/{pid}").status_code == 404

    # …and the owner can remove them
    client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL})
    assert client.delete(f"/projects/{pid}/collaborators/{other_id}").status_code == 200
    assert other_client.get(f"/projects/{pid}").status_code == 404
    assert client.delete(f"/projects/{pid}/collaborators/{other_id}").status_code == 404


def test_deleting_project_removes_collaborators():
    pid = _project("cascade")
    client.post(f"/projects/{pid}/collaborators", json={"email": OTHER_EMAIL})
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert all(p["id"] != pid for p in other_client.get("/projects").json())
