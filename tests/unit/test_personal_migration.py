"""Round-trip tests for the Feature 3 Alembic migration (``8e6070483eaf`` personal layer).

The existing migration tests assert the base schema lands and that head advanced, but not that the
two NEW tables are created, nor that ``downgrade()`` cleanly removes them. This pins both: upgrade
creates ``personal_records`` + ``attachments`` with their key columns, and a downgrade→upgrade
round-trip drops then restores exactly those tables while leaving the base schema intact.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa

import mostaql_notifier.config.secrets as secrets_mod
import mostaql_notifier.db.session as session_mod
from mostaql_notifier.config.secrets import Secrets

_HEAD = "8e6070483eaf"          # Feature 3 personal-layer migration
_INITIAL = "8d0f765b34e3"       # the revision just before it
_NEW_TABLES = {"personal_records", "attachments"}


@pytest.fixture
def isolate_globals():
    orig_get_secrets = secrets_mod.get_secrets
    orig_engine = session_mod._engine
    orig_session = session_mod._Session
    try:
        yield
    finally:
        secrets_mod.get_secrets = orig_get_secrets
        if hasattr(secrets_mod.get_secrets, "cache_clear"):
            secrets_mod.get_secrets.cache_clear()
        session_mod._engine = orig_engine
        session_mod._Session = orig_session


def _point_secrets_at(monkeypatch, url: str) -> None:
    fake = Secrets(telegram_bot_token="tok", telegram_chat_id="chat", database_url=url)
    if hasattr(secrets_mod.get_secrets, "cache_clear"):
        secrets_mod.get_secrets.cache_clear()
    monkeypatch.setattr(secrets_mod, "get_secrets", lambda: fake)
    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_Session", None)


def _tables(url: str) -> set[str]:
    eng = sa.create_engine(url, future=True)
    try:
        return set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _columns(url: str, table: str) -> set[str]:
    eng = sa.create_engine(url, future=True)
    try:
        return {c["name"] for c in sa.inspect(eng).get_columns(table)}
    finally:
        eng.dispose()


def _version(url: str) -> str:
    eng = sa.create_engine(url, future=True)
    try:
        with eng.connect() as conn:
            return conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        eng.dispose()


def test_upgrade_creates_feature3_tables(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    _point_secrets_at(monkeypatch, url)
    from mostaql_notifier.db.migrate import upgrade_head

    upgrade_head()

    names = _tables(url)
    assert _NEW_TABLES <= names, f"missing Feature 3 tables: {_NEW_TABLES - names}"

    # personal_records is the 1:1 CRM record keyed by project_id.
    pr_cols = _columns(url, "personal_records")
    assert {
        "project_id", "favorite", "status", "tags", "applied_at", "won_amount",
        "lost_reason", "notes", "board_position", "hidden", "status_changed_at",
    } <= pr_cols
    # attachments metadata (bytes live on disk; this is the row).
    att_cols = _columns(url, "attachments")
    assert {
        "id", "project_id", "original_name", "stored_name", "file_type",
        "content_type", "size_bytes", "uploaded_at",
    } <= att_cols


def test_downgrade_then_upgrade_round_trips(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    _point_secrets_at(monkeypatch, url)
    from alembic import command
    from mostaql_notifier.db import migrate as migrate_mod

    # Scope to the Feature-3 revision specifically: `upgrade_head` now targets the later Feature-4
    # head, so we upgrade to `_HEAD` explicitly to keep this a focused Feature-3 round-trip.
    cfg = migrate_mod._alembic_cfg()
    command.upgrade(cfg, _HEAD)
    assert _NEW_TABLES <= _tables(url)
    assert _version(url) == _HEAD

    # Downgrade exactly the Feature 3 revision.
    command.downgrade(cfg, _INITIAL)
    after_down = _tables(url)
    assert not (_NEW_TABLES & after_down), "downgrade must drop the Feature 3 tables"
    assert "projects" in after_down  # base schema is untouched
    assert _version(url) == _INITIAL

    # Re-upgrade restores them (a clean, reversible migration).
    command.upgrade(cfg, _HEAD)
    assert _NEW_TABLES <= _tables(url)
    assert _version(url) == _HEAD
