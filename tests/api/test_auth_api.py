"""T009 — auth gate: login/logout/status and route protection."""
from __future__ import annotations


def test_unauthenticated_projects_returns_401_when_auth_enabled(api_env):
    client = api_env.client(auth_enabled=True, password="secret")
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_login_wrong_password_returns_401(api_env):
    client = api_env.client(auth_enabled=True, password="secret")
    resp = client.post("/api/auth/login", json={"password": "nope"})
    assert resp.status_code == 401


def test_login_correct_password_sets_cookie_and_unlocks(api_env):
    client = api_env.client(auth_enabled=True, password="secret")
    resp = client.post("/api/auth/login", json={"password": "secret"})
    assert resp.status_code == 200
    # The Set-Cookie response includes the session cookie.
    set_cookie = resp.headers.get("set-cookie", "")
    assert "mn_session" in set_cookie
    # TestClient retains the cookie; the gated route now succeeds.
    follow = client.get("/api/projects")
    assert follow.status_code == 200


def test_auth_disabled_bypasses_gate(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/projects")
    assert resp.status_code == 200


def test_status_reflects_authentication_state(api_env):
    client = api_env.client(auth_enabled=True, password="secret")

    before = client.get("/api/auth/status")
    assert before.status_code == 200
    body = before.json()
    assert body["auth_enabled"] is True
    assert body["authenticated"] is False

    client.post("/api/auth/login", json={"password": "secret"})

    after = client.get("/api/auth/status")
    assert after.json()["authenticated"] is True


def test_status_when_auth_disabled_reports_authenticated(api_env):
    client = api_env.client(auth_enabled=False)
    body = client.get("/api/auth/status").json()
    assert body["auth_enabled"] is False
    assert body["authenticated"] is True


def test_logout_clears_session(api_env):
    client = api_env.client(auth_enabled=True, password="secret")
    client.post("/api/auth/login", json={"password": "secret"})
    assert client.get("/api/projects").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/projects").status_code == 401
