"""Engine / session factory built from DATABASE_URL (constitution X — portable)."""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from ..config.secrets import get_secrets
from .base import Base

_engine = None
_Session: sessionmaker | None = None


def _make_engine(url: str):
    engine = sa.create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _rec):  # enforce FKs on SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = get_secrets().database_url
        # ensure the sqlite directory exists for the default ./data path
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            if path and path not in (":memory:",):
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        _engine = _make_engine(url)
        _Session = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    get_engine()
    assert _Session is not None
    return _Session


def create_all() -> None:
    """Create tables directly (used by tests / first-run bootstrap fallback)."""
    Base.metadata.create_all(get_engine())
