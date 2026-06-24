"""Shared fixtures for the dashboard API tests.

Points Feature 1's shared session layer at a per-test temp SQLite DB (so the API exercises the
real engine + WAL pragmas), seeds the default settings, and builds a Starlette ``TestClient``
with auth either disabled (default) or enabled. Row factories produce valid ORM instances so
each test only sets the fields it cares about.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mostaql_notifier.config import secrets as secrets_mod
from mostaql_notifier.config.settings_store import seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db import session as session_mod
from mostaql_notifier.db.models import Client, Project, ProjectStatus, ScrapeRun


def _reset_engine_to(url: str) -> None:
    session_mod._engine = None
    session_mod._Session = None
    secrets_mod.get_secrets.cache_clear()


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Configure env + shared session layer for a temp DB; return a small handle.

    Use ``api_env.client(auth_enabled=..., password=...)`` to build a TestClient, and
    ``api_env.session()`` for a write session to seed rows.
    """
    db_path = tmp_path / "api_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Pin CORS origin so tests are hermetic (independent of the developer's real .env).
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-session-secret")
    # default: auth disabled (overridden per client())
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "false")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    _reset_engine_to(f"sqlite:///{db_path}")

    from mostaql_notifier.db.session import create_all, get_sessionmaker

    create_all()
    Session = get_sessionmaker()
    with Session() as s:
        seed_defaults(s)

    class Handle:
        def session(self):
            return Session()

        def client(self, auth_enabled: bool = False, password: str = "") -> TestClient:
            monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true" if auth_enabled else "false")
            monkeypatch.setenv("DASHBOARD_PASSWORD", password)
            secrets_mod.get_secrets.cache_clear()
            from mostaql_notifier.api.app import create_app

            return TestClient(create_app())

    return Handle()


# --- row factories (valid by default; override only what a test needs) ---

def _utc(dt: datetime | None = None) -> datetime:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)


def make_client(session, **over) -> Client:
    n = over.pop("_n", 1)
    defaults = dict(
        mostaql_id=f"derived:client{n}",
        name=f"عميل {n}",
        hiring_rate=80.0,
        projects_posted=5,
        projects_open=2,
        hires_count=3,
        avg_rating=4.5,
        reviews_count=10,
        total_spent=1000,
        country="مصر",
        member_since="2020",
        verified=True,
        last_refreshed_at=_utc(),
        first_seen_at=_utc(),
        raw={},
    )
    defaults.update(over)
    c = Client(**defaults)
    session.add(c)
    session.flush()
    return c


def make_project(session, **over) -> Project:
    n = over.pop("_n", 1)
    defaults = dict(
        mostaql_id=f"proj{n}",
        title=f"مشروع تطوير {n}",
        description="وصف المشروع",
        url=f"https://mostaql.com/project/{n}",
        category="development",
        skills=["python", "برمجة"],
        budget_min=100,
        budget_max=500,
        currency="USD",
        bids_count=3,
        posted_at=_utc(),
        scraped_at=_utc(),
        site_status=ProjectStatus.open,
        eval_status=models.EvalStatus.qualified,
        tier=1,
        notified=False,
        raw={},
    )
    defaults.update(over)
    p = Project(**defaults)
    session.add(p)
    session.flush()
    return p


def make_scrape_run(session, **over) -> ScrapeRun:
    defaults = dict(
        started_at=_utc() - timedelta(minutes=5),
        finished_at=_utc(),
        found_count=10,
        new_count=2,
        updated_count=1,
        error_count=0,
        status=models.RunStatus.success,
    )
    defaults.update(over)
    r = ScrapeRun(**defaults)
    session.add(r)
    session.flush()
    return r
