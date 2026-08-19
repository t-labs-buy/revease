"""Accounts and per-user isolation.

The isolation tests are the important ones: they assert that a second account
cannot see, read, or mutate the first account's space through any route, and that
private routes refuse anonymous callers outright."""

from __future__ import annotations

from app.auth import hash_password, verify_password
from tests.helpers import PASSWORD, anon, client, make_client, other_client


# --------------------------------------------------------------------------- #
# passwords & tokens
# --------------------------------------------------------------------------- #
def test_password_hash_roundtrip_and_rejection():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"  # never stored in the clear
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_long_passwords_are_not_truncated_at_72_bytes():
    """bcrypt truncates at 72 bytes; the sha256 pre-hash means these differ."""
    base = "x" * 80
    h = hash_password(base + "AAAA")
    assert not verify_password(base + "BBBB", h)


def test_verify_password_rejects_a_malformed_hash():
    assert not verify_password("anything", "not-a-bcrypt-hash")


# --------------------------------------------------------------------------- #
# register / login / me
# --------------------------------------------------------------------------- #
def test_register_creates_the_account_without_signing_you_in():
    """Registering must not hand back a session — the user goes to the login
    screen and enters their password once more."""
    r = anon.post(
        "/auth/register",
        json={"email": "no-autologin@example.com", "password": PASSWORD, "name": "No Autologin"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "no-autologin@example.com"
    assert body["name"] == "No Autologin"
    assert "access_token" not in body
    assert "token" not in body
    # nothing about that call authenticated the caller
    assert anon.get("/auth/me").status_code == 401

    # ...and the account works once they actually log in
    login = anon.post(
        "/auth/login", json={"email": "no-autologin@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_a_new_space_is_seeded_with_sample_content():
    c = make_client("fresh-user@example.com", name="Fresh")
    me = c.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "fresh-user@example.com"
    assert me.json()["name"] == "Fresh"
    # a brand-new space starts with the sample content, not empty pages
    assert len(c.get("/skills").json()) >= 1
    assert len(c.get("/kb").json()) >= 1


def test_register_rejects_a_duplicate_email_case_insensitively():
    r = anon.post(
        "/auth/register", json={"email": "OWNER@example.com", "password": PASSWORD}
    )
    assert r.status_code == 409


def test_register_rejects_a_short_password():
    r = anon.post("/auth/register", json={"email": "shorty@example.com", "password": "abc"})
    assert r.status_code == 422


def test_register_rejects_an_invalid_email():
    r = anon.post("/auth/register", json={"email": "not-an-email", "password": PASSWORD})
    assert r.status_code == 422


def test_login_succeeds_and_is_case_insensitive_on_email():
    r = anon.post("/auth/login", json={"email": "Owner@Example.COM", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["token_type"] == "bearer"
    assert r.json()["expires_in"] > 0


def test_login_with_a_wrong_password_is_401_and_does_not_leak_existence():
    """A wrong password and an email that was never registered must be
    indistinguishable, and both must carry a message the UI can show."""
    wrong = anon.post("/auth/login", json={"email": "owner@example.com", "password": "nope!!!!!"})
    missing = anon.post("/auth/login", json={"email": "ghost@example.com", "password": "nope!!!!!"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["detail"] == missing.json()["detail"] == "Invalid email or password"


# --------------------------------------------------------------------------- #
# anonymous access is refused
# --------------------------------------------------------------------------- #
def test_private_routes_reject_anonymous_callers():
    assert anon.get("/projects").status_code == 401
    assert anon.post("/projects", json={"name": "x"}).status_code == 401
    assert anon.get("/sessions").status_code == 401
    assert anon.get("/skills").status_code == 401
    assert anon.get("/kb").status_code == 401
    assert anon.get("/packages").status_code == 401
    assert anon.get("/shares").status_code == 401
    assert anon.get("/auth/me").status_code == 401


def test_a_malformed_or_forged_token_is_rejected():
    assert anon.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert anon.get("/auth/me", headers={"Authorization": "notbearer x"}).status_code == 401


def test_public_routes_stay_public():
    assert anon.get("/healthz").status_code == 200
    assert anon.get("/voices").status_code == 200


# --------------------------------------------------------------------------- #
# isolation between spaces
# --------------------------------------------------------------------------- #
def test_projects_are_invisible_to_another_account():
    pid = client.post("/projects", json={"name": "private flow"}).json()["id"]

    assert pid in [p["id"] for p in client.get("/projects").json()]
    assert pid not in [p["id"] for p in other_client.get("/projects").json()]


def test_another_account_gets_404_not_403_on_someone_elses_project():
    """404, so the response never confirms that the id exists at all."""
    pid = client.post("/projects", json={"name": "not yours"}).json()["id"]

    assert other_client.get(f"/projects/{pid}").status_code == 404
    assert other_client.delete(f"/projects/{pid}").status_code == 404
    assert other_client.post(f"/projects/{pid}/favorite").status_code == 404
    assert other_client.get(f"/projects/{pid}/graph").status_code == 404
    assert other_client.get(f"/projects/{pid}/memory").status_code == 404
    assert other_client.get(f"/projects/{pid}/video").status_code == 404
    assert other_client.get(f"/projects/{pid}/document").status_code == 404
    assert other_client.get(f"/projects/{pid}/shares").status_code == 404
    assert other_client.post(f"/projects/{pid}/share", json={"kind": "doc"}).status_code == 404
    assert other_client.post(f"/projects/{pid}/autoedit").status_code == 404
    assert other_client.get(f"/projects/{pid}/document/export").status_code == 404
    assert other_client.post(f"/projects/{pid}/rewrite", json={"lines": ["a"]}).status_code == 404

    # and it is still intact for its owner after all that
    assert client.get(f"/projects/{pid}").status_code == 200


def test_another_account_cannot_create_a_session_in_your_project():
    pid = client.post("/projects", json={"name": "session guard"}).json()["id"]
    r = other_client.post(
        "/sessions", json={"project_id": pid, "source_type": "recorder"}
    )
    assert r.status_code == 404


def test_another_account_cannot_touch_your_session():
    pid = client.post("/projects", json={"name": "session owner"}).json()["id"]
    sid = client.post(
        "/sessions", json={"project_id": pid, "source_type": "recorder"}
    ).json()["id"]

    assert other_client.get(f"/sessions/{sid}").status_code == 404
    assert other_client.get(f"/sessions/{sid}/status").status_code == 404
    assert other_client.post(f"/sessions/{sid}/complete", json={}).status_code == 404
    assert other_client.post(f"/sessions/{sid}/reprocess").status_code == 404
    assert (
        other_client.post(f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "webm"})
    ).status_code == 404
    assert (
        other_client.patch(f"/sessions/{sid}/trim", json={"start_ms": 0, "end_ms": 10})
    ).status_code == 404


def test_session_list_only_shows_your_own_captures():
    pid = client.post("/projects", json={"name": "listing"}).json()["id"]
    sid = client.post(
        "/sessions", json={"project_id": pid, "source_type": "recorder"}
    ).json()["id"]

    assert sid in [s["id"] for s in client.get("/sessions").json()]
    assert sid not in [s["id"] for s in other_client.get("/sessions").json()]
    # and scoping by someone else's project id is a 404, not an empty list
    assert other_client.get("/sessions", params={"project_id": pid}).status_code == 404


def test_skills_articles_and_packages_are_per_user():
    skill = client.post("/skills", json={"name": "My private skill"}).json()
    article = client.post("/kb", json={"title": "My private note"}).json()
    package = client.post("/packages", json={"name": "My private brand"}).json()

    assert skill["id"] not in [s["id"] for s in other_client.get("/skills").json()]
    assert article["id"] not in [a["id"] for a in other_client.get("/kb").json()]
    assert package["id"] not in [p["id"] for p in other_client.get("/packages").json()]

    assert other_client.get(f"/skills/{skill['id']}").status_code == 404
    assert other_client.get(f"/kb/{article['id']}").status_code == 404
    assert other_client.get(f"/packages/{package['id']}").status_code == 404

    assert other_client.put(
        f"/skills/{skill['id']}", json={"name": "hijacked"}
    ).status_code == 404
    assert other_client.delete(f"/skills/{skill['id']}").status_code == 404
    assert other_client.delete(f"/kb/{article['id']}").status_code == 404
    assert other_client.delete(f"/packages/{package['id']}").status_code == 404

    # the owner's rows survived every one of those attempts
    assert client.get(f"/skills/{skill['id']}").json()["name"] == "My private skill"
    assert client.get(f"/kb/{article['id']}").status_code == 200
    assert client.get(f"/packages/{package['id']}").status_code == 200


def test_media_upload_is_authorized_against_the_key_owner():
    pid = client.post("/projects", json={"name": "media guard"}).json()["id"]
    sid = client.post(
        "/sessions", json={"project_id": pid, "source_type": "recorder"}
    ).json()["id"]
    target = client.post(
        f"/sessions/{sid}/assets", json={"kind": "raw_video", "ext": "webm"}
    ).json()

    # anonymous and cross-account writes are refused; the owner's write works
    assert anon.put(target["url"], content=b"evil").status_code == 401
    assert other_client.put(target["url"], content=b"evil").status_code == 404
    assert client.put(target["url"], content=b"\x00real").status_code == 204

    # keys outside the client-writable namespaces are refused outright
    assert client.put("/media/renders/anything.mp4", content=b"x").status_code == 403


def test_deleting_your_project_does_not_touch_another_account():
    mine = client.post("/projects", json={"name": "mine to delete"}).json()["id"]
    theirs = other_client.post("/projects", json={"name": "theirs to keep"}).json()["id"]

    assert client.delete(f"/projects/{mine}").status_code == 204
    assert other_client.get(f"/projects/{theirs}").status_code == 200
