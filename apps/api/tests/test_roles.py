"""Role-based access: admins see every space, users only their own.

The admin account comes from REFRACT_ADMIN_EMAILS (set in conftest before the
app imports), which is the same bootstrap path a deployment uses."""

from __future__ import annotations

from tests.helpers import client as user_client, make_client

admin_client = make_client("admin@example.com", name="Admin")


def _me(c):
    return c.get("/auth/me").json()


def test_bootstrap_roles():
    assert _me(admin_client)["role"] == "admin"
    assert _me(user_client)["role"] == "user"


def test_admin_sees_all_projects_with_owner_labels():
    mine = user_client.post("/projects", json={"name": "roles-user-proj"}).json()
    admin_client.post("/projects", json={"name": "roles-admin-proj"})

    # default scope stays personal, even for the admin
    names = [p["name"] for p in admin_client.get("/projects").json()]
    assert "roles-admin-proj" in names and "roles-user-proj" not in names

    # scope=all widens for the admin, labelling other people's projects
    all_projects = admin_client.get("/projects?scope=all").json()
    theirs = next(p for p in all_projects if p["id"] == mine["id"])
    assert theirs["owner_email"] == "owner@example.com"
    own = next(p for p in all_projects if p["name"] == "roles-admin-proj")
    assert own["owner_email"] is None

    # scope=all is silently ignored for a regular user
    names = [p["name"] for p in user_client.get("/projects?scope=all").json()]
    assert "roles-admin-proj" not in names

    # admin can open another user's project; the reverse stays a 404
    assert admin_client.get(f"/projects/{mine['id']}").status_code == 200
    admin_proj = next(p for p in all_projects if p["name"] == "roles-admin-proj")
    assert user_client.get(f"/projects/{admin_proj['id']}").status_code == 404


def test_admin_user_management():
    admin_id = _me(admin_client)["id"]
    user_id = _me(user_client)["id"]

    # listing is admin-only
    assert user_client.get("/admin/users").status_code == 403
    users = admin_client.get("/admin/users").json()
    assert {u["email"] for u in users} >= {"admin@example.com", "owner@example.com"}

    # promote, use, demote — an existing token picks the new role up immediately
    r = admin_client.patch(f"/admin/users/{user_id}/role", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert user_client.get("/admin/users").status_code == 200
    r = admin_client.patch(f"/admin/users/{user_id}/role", json={"role": "user"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    assert user_client.get("/admin/users").status_code == 403

    # you cannot change your own role, and bootstrap admins cannot be demoted
    assert admin_client.patch(f"/admin/users/{admin_id}/role", json={"role": "user"}).status_code == 400
