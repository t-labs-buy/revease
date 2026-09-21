"""Admin password reset: sets a new password and revokes every token issued
before the change, while the login that follows works normally."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import PASSWORD, make_client

admin_client = make_client("admin@example.com", name="Admin")

EMAIL = "pw-user@example.com"


def _login(email: str, password: str):
    return TestClient(app).post("/auth/login", json={"email": email, "password": password})


def _bearer(token: str) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_admin_resets_another_users_password():
    user = make_client(EMAIL, name="PW")
    user_id = user.get("/auth/me").json()["id"]
    admin_id = admin_client.get("/auth/me").json()["id"]

    # admin-only
    assert user.post(f"/admin/users/{admin_id}/password", json={"new_password": "hijack-attempt-1"}).status_code == 403
    # not for yourself, not for unknown ids, not too short — nothing changes on any of these
    assert admin_client.post(f"/admin/users/{admin_id}/password", json={"new_password": "my-own-new-pass"}).status_code == 400
    assert admin_client.post("/admin/users/nope/password", json={"new_password": "whatever-pass-1"}).status_code == 404
    assert admin_client.post(f"/admin/users/{user_id}/password", json={"new_password": "short"}).status_code == 422
    assert user.get("/auth/me").status_code == 200

    r = admin_client.post(f"/admin/users/{user_id}/password", json={"new_password": "temp-pass-from-admin"})
    assert r.status_code == 204, r.text

    # the user's old session is out; the old password no longer works; the new one does
    assert user.get("/auth/me").status_code == 401
    assert _login(EMAIL, PASSWORD).status_code == 401
    r = _login(EMAIL, "temp-pass-from-admin")
    assert r.status_code == 200
    assert _bearer(r.json()["access_token"]).get("/auth/me").status_code == 200
    # the admin's own session is untouched
    assert admin_client.get("/auth/me").status_code == 200

    # restore for other modules
    assert admin_client.post(f"/admin/users/{user_id}/password", json={"new_password": PASSWORD}).status_code == 204
