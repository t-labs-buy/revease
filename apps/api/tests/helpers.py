"""Shared test clients.

Every private route needs a bearer token, so tests talk to the API through a
client that already carries one. `other_client` is a second, unrelated account —
use it to assert that one user's space is invisible to another. `anon` carries no
token at all, for checking that routes actually refuse anonymous callers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

PASSWORD = "test-password-1234"


def make_client(email: str, name: str = "", password: str = PASSWORD) -> TestClient:
    """A TestClient authenticated as `email`, registering the account if needed.

    Registration doesn't issue a token, so this always logs in afterwards — the
    same two-step the web app does."""
    client = TestClient(app)
    created = client.post(
        "/auth/register", json={"email": email, "password": password, "name": name}
    )
    # 409 => already registered by an earlier test module, which is fine.
    assert created.status_code in (201, 409), created.text

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


client = make_client("owner@example.com", name="Owner")
other_client = make_client("other@example.com", name="Other")
anon = TestClient(app)
