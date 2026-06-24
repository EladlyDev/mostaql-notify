"""Exhaustive tests for the dashboard auth/security layer.

Covers the signed-cookie session gate (``mn_session``), the auth routes
(login/logout/status), tampered/forged-cookie rejection, the auth-disabled bypass,
the constant-time ``password_matches`` helper, the fail-loud ``require_dashboard`` /
``create_app`` startup gate, and the credentialed CORS configuration.

These tests only read the source under test; they never modify it.
"""
from __future__ import annotations

import pytest
from itsdangerous import URLSafeTimedSerializer

from mostaql_notifier.api.security import (
    SESSION_COOKIE,
    password_matches,
)
from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.config.secrets import Secrets, require_dashboard

from .conftest import make_project

PROTECTED_ROUTES = ("/api/projects", "/api/home", "/api/settings", "/api/projects/1")

# The serializer contract enforced by ``security._serializer``.
_SESSION_SALT = "mn-dashboard-session"
_SESSION_SECRET = "test-session-secret"  # set by the conftest fixture
_SESSION_PAYLOAD = "ok"


def _set_cookie_header(response) -> str:
    """Concatenate all Set-Cookie header values from a response for inspection."""
    # httpx exposes multi-valued headers via .get_list / multi_items
    headers = response.headers
    parts = headers.get_list("set-cookie") if hasattr(headers, "get_list") else []
    if not parts:
        raw = headers.get("set-cookie")
        parts = [raw] if raw else []
    return " || ".join(parts)


def _seed_project_id1(api_env) -> None:
    """Insert one project so ``/api/projects/1`` resolves to a real row (PK starts at 1)."""
    with api_env.session() as s:
        proj = make_project(s)
        s.commit()
        assert proj.id == 1, "first seeded project should take primary key 1"


# ---------------------------------------------------------------------------
# 1. Auth-enabled gate (happy path through login/status/logout)
# ---------------------------------------------------------------------------

def test_unauthenticated_protected_routes_return_401(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    for route in PROTECTED_ROUTES:
        resp = client.get(route)
        assert resp.status_code == 401, f"{route} should be 401 when unauthenticated"


def test_login_wrong_password_returns_401(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    resp = client.post("/api/auth/login", json={"password": "nope"})
    assert resp.status_code == 401
    # No session cookie should be set on a failed login.
    assert SESSION_COOKIE not in _set_cookie_header(resp)


def test_login_correct_password_sets_session_cookie(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    resp = client.post("/api/auth/login", json={"password": "pw"})
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True, "auth_enabled": True}

    set_cookie = _set_cookie_header(resp)
    assert SESSION_COOKIE in set_cookie, "login must set the mn_session cookie"
    lowered = set_cookie.lower()
    assert "httponly" in lowered, "session cookie must be HttpOnly"
    assert "samesite=lax" in lowered, "session cookie must be SameSite=Lax"
    assert "path=/" in lowered, "session cookie must be Path=/"
    # secure=False for local HTTP — the literal "secure" attr must be absent.
    assert "secure" not in lowered, "session cookie must NOT be Secure (local HTTP)"


def test_protected_routes_accessible_after_login(api_env):
    _seed_project_id1(api_env)
    client = api_env.client(auth_enabled=True, password="pw")
    login = client.post("/api/auth/login", json={"password": "pw"})
    assert login.status_code == 200
    # TestClient retains the cookie jar across requests.
    for route in PROTECTED_ROUTES:
        resp = client.get(route)
        assert resp.status_code == 200, f"{route} should be 200 after login"


def test_status_before_and_after_login(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    before = client.get("/api/auth/status")
    assert before.status_code == 200
    assert before.json() == {"authenticated": False, "auth_enabled": True}

    client.post("/api/auth/login", json={"password": "pw"})

    after = client.get("/api/auth/status")
    assert after.status_code == 200
    assert after.json() == {"authenticated": True, "auth_enabled": True}


def test_logout_clears_cookie_and_revokes_access(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    client.post("/api/auth/login", json={"password": "pw"})
    # Sanity: authenticated now.
    assert client.get("/api/projects").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False, "auth_enabled": True}
    # logout must emit a cookie-clearing Set-Cookie for mn_session.
    assert SESSION_COOKIE in _set_cookie_header(logout)

    # The TestClient honoured the delete; protected routes are gated again.
    assert client.get("/api/auth/status").json()["authenticated"] is False
    for route in PROTECTED_ROUTES:
        assert client.get(route).status_code == 401, f"{route} should be 401 after logout"


# ---------------------------------------------------------------------------
# 2. Tampered / forged cookies (auth enabled)
# ---------------------------------------------------------------------------

def test_garbage_cookie_is_rejected(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/api/projects").status_code == 401


def test_valid_looking_but_wrong_signature_cookie_rejected(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    # A structurally token-like value with a bogus signature segment.
    client.cookies.set(SESSION_COOKIE, "Im9rIg.AAAAAA.deadbeefdeadbeefdeadbeef")
    assert client.get("/api/projects").status_code == 401


def test_token_signed_with_wrong_secret_rejected(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    forged = URLSafeTimedSerializer("wrong-secret", salt=_SESSION_SALT).dumps(_SESSION_PAYLOAD)
    client.cookies.set(SESSION_COOKIE, forged)
    assert client.get("/api/projects").status_code == 401, "wrong-secret signature must be rejected"


def test_token_signed_with_wrong_salt_rejected(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    # Right secret, wrong salt — itsdangerous must still reject it.
    forged = URLSafeTimedSerializer(_SESSION_SECRET, salt="not-the-salt").dumps(_SESSION_PAYLOAD)
    client.cookies.set(SESSION_COOKIE, forged)
    assert client.get("/api/projects").status_code == 401, "wrong-salt signature must be rejected"


def test_correctly_signed_token_grants_access(api_env):
    """Documents the signing contract: same secret + salt -> accepted without a login call."""
    _seed_project_id1(api_env)
    client = api_env.client(auth_enabled=True, password="pw")
    good = URLSafeTimedSerializer(_SESSION_SECRET, salt=_SESSION_SALT).dumps(_SESSION_PAYLOAD)
    client.cookies.set(SESSION_COOKIE, good)
    for route in PROTECTED_ROUTES:
        assert client.get(route).status_code == 200, f"{route} should accept a validly signed token"


# ---------------------------------------------------------------------------
# 3. Auth-disabled bypass
# ---------------------------------------------------------------------------

def test_protected_routes_open_when_auth_disabled(api_env):
    _seed_project_id1(api_env)
    client = api_env.client(auth_enabled=False)
    for route in PROTECTED_ROUTES:
        assert client.get(route).status_code == 200, f"{route} should be open when auth disabled"


def test_status_reports_auth_disabled(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True, "auth_enabled": False}


@pytest.mark.parametrize("password", ["anything", "", "wrong"])
def test_login_always_succeeds_when_auth_disabled(api_env, password):
    client = api_env.client(auth_enabled=False)
    resp = client.post("/api/auth/login", json={"password": password})
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": True, "auth_enabled": False}


# ---------------------------------------------------------------------------
# 4. password_matches unit
# ---------------------------------------------------------------------------

def test_password_matches_correct():
    secrets = Secrets(dashboard_password="abc")
    assert password_matches("abc", secrets) is True


def test_password_matches_wrong():
    secrets = Secrets(dashboard_password="abc")
    assert password_matches("abd", secrets) is False


def test_password_matches_empty_candidate_vs_set_password():
    secrets = Secrets(dashboard_password="abc")
    assert password_matches("", secrets) is False


def test_password_matches_case_sensitive():
    secrets = Secrets(dashboard_password="abc")
    assert password_matches("ABC", secrets) is False


def test_password_matches_unicode():
    secrets = Secrets(dashboard_password="كلمة-سر")
    assert password_matches("كلمة-سر", secrets) is True
    assert password_matches("كلمة", secrets) is False


# ---------------------------------------------------------------------------
# 5. Fail-loud require_dashboard / create_app
# ---------------------------------------------------------------------------

def test_create_app_raises_when_enabled_without_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "some-secret")
    secrets_mod.get_secrets.cache_clear()
    try:
        from mostaql_notifier.api.app import create_app

        with pytest.raises(RuntimeError):
            create_app()
    finally:
        secrets_mod.get_secrets.cache_clear()


def test_create_app_raises_when_enabled_without_session_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pw")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    secrets_mod.get_secrets.cache_clear()
    try:
        from mostaql_notifier.api.app import create_app

        with pytest.raises(RuntimeError):
            create_app()
    finally:
        secrets_mod.get_secrets.cache_clear()


def test_require_dashboard_no_raise_when_disabled():
    secrets = Secrets(dashboard_auth_enabled=False, dashboard_password="", dashboard_session_secret="")
    # Must not raise even though password/secret are blank.
    require_dashboard(secrets)


def test_require_dashboard_no_raise_when_enabled_with_credentials():
    secrets = Secrets(
        dashboard_auth_enabled=True,
        dashboard_password="pw",
        dashboard_session_secret="sekret",
    )
    require_dashboard(secrets)


def test_require_dashboard_raises_when_enabled_missing_password():
    secrets = Secrets(
        dashboard_auth_enabled=True,
        dashboard_password="",
        dashboard_session_secret="sekret",
    )
    with pytest.raises(RuntimeError):
        require_dashboard(secrets)


# ---------------------------------------------------------------------------
# 6. CORS (credentialed, origin-restricted)
# ---------------------------------------------------------------------------

def test_cors_allows_configured_origin_with_credentials(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/auth/status", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_allows_configured_origin(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.options(
        "/api/auth/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallowed_origin_not_echoed(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/auth/status", headers={"Origin": "http://evil.com"})
    # The route still responds, but the evil origin must never be granted.
    assert resp.headers.get("access-control-allow-origin") != "http://evil.com"
