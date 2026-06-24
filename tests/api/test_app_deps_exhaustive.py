"""Exhaustive tests for the app factory, the DB-session dependency, and cross-cutting wiring.

Covers: OpenAPI/docs surface, the WAL/foreign-keys/busy_timeout pragmas applied by the shared
engine, the 503 mapping in ``deps.get_db``, CORS preflight for PUT, the public/gated routing
split, and 404/405 behavior. Source is never modified; where the real mapping is hard to drive
through the engine we also assert ``get_db`` directly via the generator protocol.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from mostaql_notifier.api.deps import get_db
from mostaql_notifier.db import session as session_mod

# --- Endpoint inventory (kept in one place for the wiring tests) ---
PUBLIC_ROUTES = [
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
    ("get", "/api/auth/status"),
]
GATED_ROUTES = [
    ("get", "/api/projects"),
    ("get", "/api/home"),
    ("get", "/api/settings"),
]


# =====================================================================================
# 1. OpenAPI / docs surface
# =====================================================================================
def test_openapi_lists_all_expected_paths(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec["paths"]
    for expected in (
        "/api/projects",
        "/api/projects/{id}",
        "/api/home",
        "/api/settings",
        "/api/auth/login",
    ):
        assert expected in paths, f"missing path {expected} in openapi"


def test_openapi_title_and_version(api_env):
    client = api_env.client(auth_enabled=False)
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Mostaql Notifier — Dashboard API"
    assert spec["info"]["version"] == "1.0.0"


def test_docs_endpoint_serves_html(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# =====================================================================================
# 2. WAL / FK / busy_timeout pragmas actually applied on the shared engine
# =====================================================================================
def test_sqlite_pragmas_applied_on_real_connection(api_env):
    # Build a client first so the lifespan/engine is materialized against the temp DB.
    api_env.client(auth_enabled=False)
    engine = session_mod.get_engine()
    with engine.connect() as conn:
        journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        fks = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert str(journal).lower() == "wal"
    assert int(fks) == 1
    assert int(busy) == 5000


# =====================================================================================
# 3. 503 on DB failure (exercise the REAL deps.get_db mapping)
# =====================================================================================
def test_route_returns_503_when_db_unreachable(api_env, monkeypatch):
    """Drive deps.get_db's real OperationalError->503 mapping end-to-end.

    Method: build a normal client, then repoint the *shared* session layer
    (``session_mod._engine`` / ``session_mod._Session``) at a sqlite engine whose file path
    lives under a nonexistent directory (``sqlite:////nonexistent/dir/x.db``). The engine is
    created lazily, so construction succeeds; the failure surfaces when ``get_db`` opens a
    connection and the route issues its first query -> ``OperationalError`` -> ``get_db`` maps
    it to ``HTTPException(503)``. We patch the module globals (not a FastAPI dependency
    override) precisely so the real ``get_db`` body runs.
    """
    client = api_env.client(auth_enabled=False)

    bad_engine = sa.create_engine("sqlite:////nonexistent/dir/x.db", future=True)
    bad_session = sessionmaker(bind=bad_engine, class_=Session, future=True)
    monkeypatch.setattr(session_mod, "_engine", bad_engine)
    monkeypatch.setattr(session_mod, "_Session", bad_session)

    resp = client.get("/api/projects")
    assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.text}"
    assert resp.json()["detail"] == "Database unavailable"


def test_get_db_unit_maps_operational_error_to_503():
    """Focused unit test: feeding an OperationalError into the live generator yields 503."""
    gen = get_db()
    next(gen)  # enter the try-block, session is open
    with pytest.raises(HTTPException) as ei:
        gen.throw(OperationalError("SELECT 1", {}, Exception("db is locked")))
    assert ei.value.status_code == 503
    assert ei.value.detail == "Database unavailable"
    gen.close()


def test_get_db_unit_maps_sessionmaker_failure_to_503(monkeypatch):
    """If the sessionmaker can't be created (SQLAlchemyError), get_db raises 503 before yield."""

    def _boom():
        raise SQLAlchemyError("engine boom")

    monkeypatch.setattr(session_mod, "get_sessionmaker", _boom)
    # get_db imported the name into its own module namespace; patch there too.
    import mostaql_notifier.api.deps as deps_mod

    monkeypatch.setattr(deps_mod, "get_sessionmaker", _boom)

    gen = get_db()
    with pytest.raises(HTTPException) as ei:
        next(gen)
    assert ei.value.status_code == 503


def test_get_db_closes_session_on_success_path(api_env):
    """The finally-block must close the yielded session even on the happy path."""
    api_env.client(auth_enabled=False)  # materialize engine against temp DB
    gen = get_db()
    sess = next(gen)
    assert isinstance(sess, Session)
    with pytest.raises(StopIteration):
        next(gen)
    # After exhaustion the finally-block has run; a closed session has no active transaction.
    assert not sess.in_transaction()


# =====================================================================================
# 4. CORS preflight for a PUT to /api/settings from the allowed origin
# =====================================================================================
def test_cors_preflight_put_settings_allowed(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.options(
        "/api/settings",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert resp.status_code in (200, 204), resp.text
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "PUT" in allow_methods or "*" in allow_methods
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallowed_origin_not_echoed(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.options(
        "/api/settings",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "PUT",
        },
    )
    # Starlette returns 400 for a disallowed preflight origin and never echoes it.
    assert resp.headers.get("access-control-allow-origin") != "http://evil.example"


# =====================================================================================
# 5. Routing / auth wiring: public vs gated split
# =====================================================================================
@pytest.mark.parametrize("method,path", PUBLIC_ROUTES)
def test_public_routes_reachable_without_session_when_auth_enabled(api_env, method, path):
    client = api_env.client(auth_enabled=True, password="hunter2")
    kwargs = {"json": {}} if method == "post" else {}
    resp = getattr(client, method)(path, **kwargs)
    # Public => not gated: anything but 401/404 proves the route exists and is ungated.
    assert resp.status_code != 401, f"{method} {path} unexpectedly gated"
    assert resp.status_code != 404, f"{method} {path} missing"


@pytest.mark.parametrize("method,path", GATED_ROUTES)
def test_gated_routes_require_session_when_auth_enabled(api_env, method, path):
    client = api_env.client(auth_enabled=True, password="hunter2")
    resp = getattr(client, method)(path)
    assert resp.status_code == 401, f"{method} {path} should be gated, got {resp.status_code}"


@pytest.mark.parametrize("method,path", GATED_ROUTES)
def test_gated_routes_open_when_auth_disabled(api_env, method, path):
    client = api_env.client(auth_enabled=False)
    resp = getattr(client, method)(path)
    assert resp.status_code != 401, f"{method} {path} should be open when auth disabled"
    assert resp.status_code != 404, f"{method} {path} missing"


# =====================================================================================
# 6. Unknown route -> 404 ; wrong method -> 405
# =====================================================================================
def test_unknown_route_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.get("/api/does-not-exist").status_code == 404


def test_wrong_method_on_projects_405(api_env):
    client = api_env.client(auth_enabled=False)
    # /api/projects exposes only GET; DELETE must be Method Not Allowed (not 404).
    assert client.delete("/api/projects").status_code == 405


def test_wrong_method_on_auth_login_405(api_env):
    client = api_env.client(auth_enabled=False)
    # /api/auth/login is POST-only.
    assert client.get("/api/auth/login").status_code == 405
