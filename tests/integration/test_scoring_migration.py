"""Round-trip tests for the Feature 4 Alembic migration (``08bb5227930f`` continuous watch scoring).

Pins that the upgrade creates the two new tables (``project_scores`` 1:1, ``project_snapshots``
append-only) with their key columns, adds ``scrape_runs.kind`` (backfilling existing rows to
``"poll"``) and the two ``personal_records.auto_status_*`` columns, admits the new ``awarded`` status
value through the ORM, and idempotently appends the ``expired_missed`` personal stage to a legacy
``personal_statuses`` row — and that a downgrade→upgrade round-trip drops then restores exactly those
deltas while leaving the base schema intact.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

import mostaql_notifier.config.secrets as secrets_mod
import mostaql_notifier.db.session as session_mod
from mostaql_notifier.config.secrets import Secrets

_HEAD = "08bb5227930f"     # Feature 4 continuous-watch-scoring migration
_PRIOR = "8e6070483eaf"    # Feature 3 personal-layer (the revision just before it)
_NEW_TABLES = {"project_scores", "project_snapshots"}


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


def test_upgrade_creates_feature4_schema(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    _point_secrets_at(monkeypatch, url)
    from mostaql_notifier.db.migrate import upgrade_head

    upgrade_head()

    names = _tables(url)
    assert _NEW_TABLES <= names, f"missing Feature 4 tables: {_NEW_TABLES - names}"

    # project_scores — latest score/breakdown + lifecycle singletons, keyed 1:1 by project_id.
    ps_cols = _columns(url, "project_scores")
    assert {
        "project_id", "score", "breakdown", "computed_at", "outcome",
        "tracking_active", "last_checked_at", "closed_observed_at", "created_at", "updated_at",
    } <= ps_cols
    # project_snapshots — append-only trajectory.
    sn_cols = _columns(url, "project_snapshots")
    assert {"id", "project_id", "captured_at", "bids_count", "site_status", "score"} <= sn_cols
    # additive columns on existing tables.
    assert "kind" in _columns(url, "scrape_runs")
    assert {"auto_status_from", "auto_status_at"} <= _columns(url, "personal_records")


def test_orm_accepts_awarded_and_outcomes_after_upgrade(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'orm.db'}"
    _point_secrets_at(monkeypatch, url)
    from sqlalchemy.orm import Session as OrmSession

    from mostaql_notifier.db.migrate import upgrade_head
    from mostaql_notifier.db.models import (
        Outcome,
        Project,
        ProjectScore,
        ProjectSnapshot,
        ProjectStatus,
    )

    upgrade_head()
    # Bind a session straight to the migrated URL (the shared session layer cached get_secrets at
    # import, so it would not see the monkeypatched URL — mirror the file's other direct-engine helpers).
    eng = sa.create_engine(url, future=True)
    try:
        with OrmSession(eng) as s:
            p = Project(mostaql_id="aw1", scraped_at=datetime.now(timezone.utc), site_status=ProjectStatus.awarded)
            s.add(p)
            s.flush()
            s.add(ProjectScore(project_id=p.id, score=80.0, breakdown={"score": 80.0}, outcome=Outcome.hired))
            s.add(ProjectSnapshot(
                project_id=p.id,
                captured_at=datetime.now(timezone.utc),
                bids_count=4,
                site_status=ProjectStatus.awarded,
                score=80.0,
            ))
            s.commit()
            got = s.get(Project, p.id)
            assert got.site_status is ProjectStatus.awarded          # new enum value round-trips
            assert got.score_row.outcome is Outcome.hired            # 1:1 relationship + outcome enum
            assert len(got.snapshots) == 1                           # trajectory relationship
    finally:
        eng.dispose()


def test_data_step_appends_expired_missed_idempotently(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'data.db'}"
    _point_secrets_at(monkeypatch, url)
    from alembic import command
    from mostaql_notifier.db import migrate as migrate_mod

    # Stand up the schema only as far as the PRIOR head, then seed a legacy personal_statuses row
    # that does NOT yet contain expired_missed and an existing scrape_run (to test kind backfill).
    cfg = migrate_mod._alembic_cfg()
    command.upgrade(cfg, _PRIOR)
    eng = sa.create_engine(url, future=True)
    legacy = [{"key": "new", "label": "جديد"}, {"key": "interested", "label": "مهتم"}]
    with eng.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO settings(key, value, value_type) VALUES (:k, :v, 'json')"),
            {"k": "personal_statuses", "v": json.dumps(legacy, ensure_ascii=False)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO scrape_runs(started_at, found_count, new_count, updated_count, "
                "error_count, status) VALUES (:t, 1, 0, 0, 0, 'success')"
            ),
            {"t": datetime.now(timezone.utc)},
        )
    eng.dispose()

    # Now run the Feature 4 migration over the legacy data.
    command.upgrade(cfg, "head")

    eng = sa.create_engine(url, future=True)
    with eng.connect() as conn:
        value = conn.execute(
            sa.text("SELECT value FROM settings WHERE key='personal_statuses'")
        ).scalar()
        statuses = json.loads(value)
        keys = [s["key"] for s in statuses]
        assert keys[:2] == ["new", "interested"], "existing stages are preserved in order"
        assert keys.count("expired_missed") == 1, "expired_missed appended exactly once (idempotent)"
        # the pre-existing scrape_run row was backfilled to the default kind.
        kind = conn.execute(sa.text("SELECT kind FROM scrape_runs LIMIT 1")).scalar()
        assert kind == "poll"
    eng.dispose()


def test_downgrade_then_upgrade_round_trips(tmp_path, monkeypatch, isolate_globals):
    url = f"sqlite:///{tmp_path / 'rt.db'}"
    _point_secrets_at(monkeypatch, url)
    from alembic import command
    from mostaql_notifier.db import migrate as migrate_mod

    migrate_mod.upgrade_head()
    assert _NEW_TABLES <= _tables(url)
    assert "kind" in _columns(url, "scrape_runs")
    assert _version(url) == _HEAD

    # Downgrade exactly the Feature 4 revision.
    command.downgrade(migrate_mod._alembic_cfg(), _PRIOR)
    after_down = _tables(url)
    assert not (_NEW_TABLES & after_down), "downgrade must drop the Feature 4 tables"
    assert "kind" not in _columns(url, "scrape_runs"), "downgrade drops scrape_runs.kind"
    assert "projects" in after_down  # base schema is untouched
    assert _version(url) == _PRIOR

    # Re-upgrade restores them (a clean, reversible migration).
    migrate_mod.upgrade_head()
    assert _NEW_TABLES <= _tables(url)
    assert _version(url) == _HEAD
