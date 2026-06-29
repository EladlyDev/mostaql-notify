"""Exhaustive branch coverage for ``worker/recheck.py`` (Feature 4, the watch-over-time loop).

Every test drives the real ``run_recheck_cycle``/helpers against a real (temp) SQLite session and a
real seeded ``SettingsStore``; only the two network/parse boundaries are faked:

* ``fetcher.get`` returns a tiny stand-in with ``.status``/``.body``/``.body_bytes`` (the exact shape
  ``classify_response`` reads), and
* ``recheck.parse_project_page`` is monkeypatched to a deterministic dict so the page contents are
  controlled per test.

``polite_delay`` is stubbed to an async no-op so tests never sleep. ``asyncio_mode=auto`` is on, so
``async def test_*`` runs directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import mostaql_notifier.worker.recheck as recheck
from mostaql_notifier.config.settings_store import (
    SettingsStore,
    app_state_set,
    seed_defaults,
)
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db.base import Base
from mostaql_notifier.db.models import (
    Client,
    Outcome,
    Project,
    ProjectScore,
    ProjectSnapshot,
    ProjectStatus,
    RunStatus,
    ScrapeRun,
    Setting,
    derive_client_key,
)
from tests.api.conftest import (
    make_client,
    make_personal_record,
    make_project,
    make_project_score,
)

NOW = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- fakes


class FakeResult:
    """Minimal ``FetchResult`` stand-in: only what ``classify_response`` touches."""

    def __init__(self, status: int = 200, body: str = "page", body_bytes: int = 50000):
        self.status = status
        self.body = body
        self.body_bytes = body_bytes


class FakeFetcher:
    """``async def get`` returning ``self.default`` (or a per-url override). Records every URL."""

    def __init__(self, default: FakeResult | None = None, by_url: dict | None = None):
        self.default = default or FakeResult()
        self.by_url = by_url or {}
        self.calls: list[str] = []

    async def get(self, url, referer=None):
        self.calls.append(url)
        return self.by_url.get(url, self.default)


class FakeSender:
    def __init__(self):
        self.alerts: list[str] = []

    async def send_alert(self, text):
        self.alerts.append(text)


# --------------------------------------------------------------------------- fixtures / helpers


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/recheck.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = Session()
    seed_defaults(session)
    # Never sleep in tests.
    monkeypatch.setattr(recheck, "polite_delay", _noop_delay)
    settings = SettingsStore(session)
    settings.reload()
    yield _Handle(Session=Session, session=session, settings=settings)
    session.close()


class _Handle:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def _noop_delay(settings, *a, **k):
    return 0.0


def set_setting(session, key: str, value, vtype: str) -> None:
    from mostaql_notifier.config.settings_store import _serialize

    row = session.get(Setting, key)
    serialized = _serialize(value, vtype)
    if row is None:
        session.add(Setting(key=key, value=serialized, value_type=vtype))
    else:
        row.value = serialized
        row.value_type = vtype
    session.commit()


def make_parse(monkeypatch, *, bids=8, status=ProjectStatus.open, client=None, raise_on=None):
    """Monkeypatch ``recheck.parse_project_page`` with a deterministic, body-dispatched parser."""

    def _parse(body, awarded_markers=None):
        if raise_on is not None and raise_on in body:
            raise ValueError("parse boom")
        return {"bids_count": bids, "site_status": status, "client": client or {}}

    monkeypatch.setattr(recheck, "parse_project_page", _parse)


def seed_tracked(session, *, n, status=ProjectStatus.open, last_checked_at=None,
                 closed_observed_at=None, tracking_active=True, score=70.0, with_client=True,
                 bids_count=3, url=None):
    """Create a project + 1:1 ProjectScore (optionally a client) wired for the re-check selector."""
    client_id = None
    if with_client:
        c = make_client(session, _n=n)
        client_id = c.id
    p = make_project(
        session, _n=n, client_id=client_id, site_status=status, bids_count=bids_count,
        url=url or f"https://mostaql.com/project/{n}",
    )
    make_project_score(
        session, project=p, score=score, computed_at=NOW - timedelta(days=10),
        last_checked_at=last_checked_at, closed_observed_at=closed_observed_at,
        tracking_active=tracking_active,
    )
    session.commit()
    return p


# =========================================================================== tests


# 1) Owner pause: quiet skip, no run row.
async def test_watcher_paused_returns_none_no_run(db):
    set_setting(db.session, "watcher_paused", True, "bool")
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run is None
    assert db.session.query(ScrapeRun).count() == 0
    assert fetcher.calls == []


# 2) Breaker already paused at cycle start: run is blocked, no fetches.
async def test_breaker_paused_finishes_blocked_no_fetch(db):
    # is_paused() compares against real utcnow(), so use a far-future resume time.
    app_state_set(db.session, "cb_resume_at", "2099-01-01T00:00:00+00:00")
    seed_tracked(db.session, n=1)
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.status is RunStatus.blocked
    assert "paused" in (run.notes or "").lower()
    assert run.finished_at is not None
    assert fetcher.calls == []


# 3a) Stalest-first selection (NULL first, then oldest), capped by recheck_batch_size.
async def test_due_selection_order_and_batch_cap(db, monkeypatch):
    set_setting(db.session, "recheck_batch_size", 2, "int")
    make_parse(monkeypatch)
    # p_null: never checked; p_old: checked long ago; p_recent_due: checked older than null/old but
    # still due. With batch=2 only the two stalest (NULL, then oldest timestamp) are picked.
    seed_tracked(db.session, n=1, last_checked_at=None, url="https://x/null")
    seed_tracked(db.session, n=2, last_checked_at=NOW - timedelta(days=5), url="https://x/old")
    seed_tracked(db.session, n=3, last_checked_at=NOW - timedelta(hours=1), url="https://x/newer")
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 2
    assert set(fetcher.calls) == {"https://x/null", "https://x/old"}
    assert "https://x/newer" not in fetcher.calls


# 3b) Recently-checked (within recheck_min_interval_seconds) is NOT due.
async def test_recently_checked_not_due(db, monkeypatch):
    make_parse(monkeypatch)
    seed_tracked(db.session, n=1, last_checked_at=NOW)  # checked "now" -> inside min interval
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 0
    assert fetcher.calls == []


# 3c) Only tracking_active=True rows are selected.
async def test_inactive_tracking_not_selected(db, monkeypatch):
    make_parse(monkeypatch)
    seed_tracked(db.session, n=1, tracking_active=False)
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 0


# 3d) Closed within grace IS eligible; open always eligible.
async def test_closed_within_grace_is_eligible(db, monkeypatch):
    make_parse(monkeypatch, status=ProjectStatus.closed)
    seed_tracked(
        db.session, n=1, status=ProjectStatus.closed,
        closed_observed_at=NOW - timedelta(hours=1),  # well within 72h grace
        url="https://x/closed-fresh",
    )
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 1
    assert "https://x/closed-fresh" in fetcher.calls


# 4) Pre-select retirement sweep: closed past grace is retired WITHOUT a fetch.
async def test_pre_select_sweep_retires_aged_closed_without_fetch(db, monkeypatch):
    make_parse(monkeypatch)
    grace = db.settings.get_int("tracking_grace_hours")
    p = seed_tracked(
        db.session, n=1, status=ProjectStatus.closed,
        closed_observed_at=NOW - timedelta(hours=grace + 1),  # strictly past grace
        url="https://x/aged",
    )
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    score = db.session.get(ProjectScore, p.id)
    assert score.tracking_active is False
    assert fetcher.calls == []  # aged-out rows are never fetched
    assert run.found_count == 0
    assert db.session.query(ProjectSnapshot).count() == 0


# 5) Happy path OPEN: bids/status synced, re-scored, snapshot appended, outcome open, committed.
async def test_recheck_one_open_happy_path(db, monkeypatch):
    make_parse(monkeypatch, bids=42, status=ProjectStatus.open,
               client={"name": "c", "member_since": "2019"})
    p = seed_tracked(db.session, n=1, score=12.5, bids_count=3)  # sentinel score to prove re-score
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    proj = db.session.get(Project, p.id)
    score = db.session.get(ProjectScore, p.id)
    snaps = db.session.query(ProjectSnapshot).filter_by(project_id=p.id).all()
    assert proj.bids_count == 42
    assert proj.site_status is ProjectStatus.open
    assert score.computed_at == NOW          # re-scored this cycle (score_service stamps now)
    assert score.outcome is Outcome.open
    assert score.last_checked_at == NOW
    assert score.closed_observed_at is None  # still open -> never stamped
    assert len(snaps) == 1
    assert snaps[0].score == score.score     # snapshot carries the freshly-computed score
    assert snaps[0].bids_count == 42
    assert run.status is RunStatus.success
    # Committed: visible from a brand-new session.
    with db.Session() as s2:
        assert s2.get(ProjectScore, p.id).last_checked_at == NOW


# 6) Freeze-on-close: NOT re-scored, snapshot carries frozen score, closed_observed_at stamped now.
async def test_recheck_one_freeze_on_close(db, monkeypatch):
    make_parse(monkeypatch, bids=99, status=ProjectStatus.closed)
    p = seed_tracked(db.session, n=1, status=ProjectStatus.open, score=70.0)
    frozen_computed_at = db.session.get(ProjectScore, p.id).computed_at
    fetcher, sender = FakeFetcher(), FakeSender()

    await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    score = db.session.get(ProjectScore, p.id)
    snap = db.session.query(ProjectSnapshot).filter_by(project_id=p.id).one()
    assert score.score == 70.0                       # frozen — not recomputed
    assert score.computed_at == frozen_computed_at   # scorer never ran
    assert snap.score == 70.0                         # snapshot carries the frozen score
    assert score.outcome is Outcome.closed_no_hire
    assert score.closed_observed_at == NOW            # first non-open observation stamped


# 6b) closed_observed_at is stamped on the FIRST non-open observation only (never overwritten).
async def test_closed_observed_at_not_overwritten(db, monkeypatch):
    make_parse(monkeypatch, status=ProjectStatus.closed)
    earlier = NOW - timedelta(hours=2)  # already observed closed earlier, still within grace
    p = seed_tracked(
        db.session, n=1, status=ProjectStatus.closed, closed_observed_at=earlier,
        last_checked_at=NOW - timedelta(days=1),
    )
    fetcher, sender = FakeFetcher(), FakeSender()

    await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert db.session.get(ProjectScore, p.id).closed_observed_at == earlier  # untouched


# 7) Grace retirement inside _recheck_one (selected at the boundary, then retired).
async def test_recheck_one_grace_retirement(db, monkeypatch):
    make_parse(monkeypatch, status=ProjectStatus.closed)
    grace = db.settings.get_int("tracking_grace_hours")
    # closed_observed_at == grace boundary: passes selection (>= cutoff) AND triggers retirement
    # (now - observed >= grace) inside _recheck_one.
    p = seed_tracked(
        db.session, n=1, status=ProjectStatus.closed,
        closed_observed_at=NOW - timedelta(hours=grace),
    )
    fetcher, sender = FakeFetcher(), FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 1
    score = db.session.get(ProjectScore, p.id)
    assert score.tracking_active is False
    assert score.last_checked_at == NOW
    assert db.session.query(ProjectSnapshot).filter_by(project_id=p.id).count() == 1


# 8) Block detected mid-cycle: _recheck_one returns True, cycle finishes blocked, alerts once.
async def test_block_finishes_cycle_and_alerts(db, monkeypatch):
    make_parse(monkeypatch)
    seed_tracked(db.session, n=1)
    fetcher = FakeFetcher(default=FakeResult(status=403))
    sender = FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.status is RunStatus.blocked
    assert run.finished_at is not None
    assert len(sender.alerts) == 1  # breaker transitioned -> exactly one alert
    assert db.session.query(ProjectSnapshot).count() == 0


# 8b) Challenge classification also stops the cycle (returns True).
async def test_challenge_finishes_cycle(db, monkeypatch):
    make_parse(monkeypatch)
    seed_tracked(db.session, n=1)
    # status 200 but a challenge marker in the body -> Classification.challenge.
    fetcher = FakeFetcher(default=FakeResult(status=200, body="just a moment", body_bytes=50000))
    sender = FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.status is RunStatus.blocked
    assert len(sender.alerts) == 1


# 9) Transient fetch: error_count++, project skipped (no snapshot), cycle continues -> partial.
async def test_transient_increments_error_and_skips(db, monkeypatch):
    make_parse(monkeypatch)
    p = seed_tracked(db.session, n=1)
    fetcher = FakeFetcher(default=FakeResult(status=500))
    sender = FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.error_count == 1
    assert run.status is RunStatus.partial
    assert db.session.query(ProjectSnapshot).count() == 0
    assert db.session.get(ProjectScore, p.id).last_checked_at is None  # never advanced


# 10) Per-project exception isolation: middle project raises; batch continues; found_count survives.
async def test_per_project_exception_isolated(db, monkeypatch):
    # Parser raises only for the project whose body (== url) contains BOOM.
    make_parse(monkeypatch, raise_on="BOOM")
    p1 = seed_tracked(db.session, n=1, last_checked_at=NOW - timedelta(days=3), url="https://x/ok1")
    p2 = seed_tracked(db.session, n=2, last_checked_at=NOW - timedelta(days=2), url="https://x/BOOM")
    p3 = seed_tracked(db.session, n=3, last_checked_at=NOW - timedelta(days=1), url="https://x/ok3")
    # fetcher returns body == url so the parser can dispatch on it.
    fetcher = FakeFetcher(by_url={
        "https://x/ok1": FakeResult(body="https://x/ok1"),
        "https://x/BOOM": FakeResult(body="https://x/BOOM"),
        "https://x/ok3": FakeResult(body="https://x/ok3"),
    })
    sender = FakeSender()

    run = await recheck.run_recheck_cycle(db.session, fetcher, sender, db.settings, now=NOW)

    assert run.found_count == 3          # committed before the loop; rollback can't revert it
    assert run.error_count == 1
    assert run.status is RunStatus.partial
    assert f"{p2.mostaql_id}:" in (run.notes or "")
    assert db.session.get(ProjectScore, p1.id).last_checked_at == NOW  # succeeded
    assert db.session.get(ProjectScore, p3.id).last_checked_at == NOW  # batch continued
    # The raiser rolled back: its last_checked_at keeps the seeded value, never advanced to NOW.
    assert db.session.get(ProjectScore, p2.id).last_checked_at == NOW - timedelta(days=2)


# 11) _outcome_for direct mapping.
def test_outcome_for_mapping():
    assert recheck._outcome_for(ProjectStatus.open) is Outcome.open
    assert recheck._outcome_for(ProjectStatus.awarded) is Outcome.hired
    assert recheck._outcome_for(ProjectStatus.closed) is Outcome.closed_no_hire
    assert recheck._outcome_for(ProjectStatus.unknown) is Outcome.unknown


# 12) _maybe_refresh_client: fresh -> skip; stale -> refresh; None -> create + wire.
def test_maybe_refresh_client_fresh_skips(db):
    c = make_client(db.session, _n=1, name="old", last_refreshed_at=NOW - timedelta(hours=1))
    p = make_project(db.session, _n=1, client_id=c.id)
    db.session.commit()
    data = {"client": {"name": "new", "hiring_rate": 99.0}}

    recheck._maybe_refresh_client(db.session, p, data, db.settings, NOW)

    assert c.name == "old"  # within client_refresh_hours (12h) -> untouched


def test_maybe_refresh_client_stale_refreshes(db):
    c = make_client(db.session, _n=1, name="old", hiring_rate=10.0,
                    last_refreshed_at=NOW - timedelta(days=5))
    p = make_project(db.session, _n=1, client_id=c.id)
    db.session.commit()
    data = {"client": {"name": "new", "hiring_rate": 99.0, "projects_open": 7}}

    recheck._maybe_refresh_client(db.session, p, data, db.settings, NOW)

    assert c.name == "new"
    assert c.hiring_rate == 99.0
    assert c.projects_open == 7
    assert c.last_refreshed_at == NOW


def test_maybe_refresh_client_creates_when_none(db):
    p = make_project(db.session, _n=1, client_id=None)
    db.session.commit()
    cdata = {"name": "fresh client", "member_since": "2021", "hiring_rate": 55.0}
    data = {"client": cdata}

    recheck._maybe_refresh_client(db.session, p, data, db.settings, NOW)

    assert p.client_id is not None
    created = db.session.get(Client, p.client_id)
    assert created.mostaql_id == derive_client_key("fresh client", "2021")
    assert created.name == "fresh client"
    assert created.last_refreshed_at == NOW


def test_maybe_refresh_client_none_safe_empty_data(db):
    p = make_project(db.session, _n=1, client_id=None)
    db.session.commit()

    recheck._maybe_refresh_client(db.session, p, {}, db.settings, NOW)  # no "client" key

    assert p.client_id is not None  # created from empty/derived key, no crash


# 13) _maybe_auto_status: fires only under the full gate; otherwise no-op.
def _personal(db, project, **over):
    return make_personal_record(db.session, project=project, **over)


def test_auto_status_fires_when_enabled_interested_and_closed(db):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    db.settings.reload()
    p = make_project(db.session, _n=1, site_status=ProjectStatus.closed)
    rec = _personal(db, p, status="interested", applied_at=None)
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)

    assert rec.status == "expired_missed"
    assert rec.auto_status_from == "interested"
    assert rec.auto_status_at == NOW
    assert rec.status_changed_at == NOW


def test_auto_status_skips_when_disabled(db):
    # default auto_status_personal_enabled is False
    p = make_project(db.session, _n=1, site_status=ProjectStatus.closed)
    rec = _personal(db, p, status="interested")
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)

    assert rec.status == "interested"


def test_auto_status_skips_when_still_open(db):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    db.settings.reload()
    p = make_project(db.session, _n=1, site_status=ProjectStatus.open)
    rec = _personal(db, p, status="interested")
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)

    assert rec.status == "interested"


def test_auto_status_skips_when_status_not_interested(db):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    db.settings.reload()
    p = make_project(db.session, _n=1, site_status=ProjectStatus.closed)
    rec = _personal(db, p, status="applied")
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)

    assert rec.status == "applied"  # owner already moved past interested


def test_auto_status_skips_when_applied_at_set(db):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    db.settings.reload()
    p = make_project(db.session, _n=1, site_status=ProjectStatus.awarded)
    rec = _personal(db, p, status="interested", applied_at=NOW - timedelta(days=1))
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)

    assert rec.status == "interested"  # an application was recorded -> never auto-expire


def test_auto_status_no_record_is_noop(db):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    db.settings.reload()
    p = make_project(db.session, _n=1, site_status=ProjectStatus.closed)  # no personal record
    db.session.commit()

    recheck._maybe_auto_status(db.session, p, db.settings, NOW)  # must not raise


# 13b) End-to-end auto-status via the cycle on a freshly observed close (awarded).
async def test_cycle_auto_status_on_awarded(db, monkeypatch):
    set_setting(db.session, "auto_status_personal_enabled", True, "bool")
    make_parse(monkeypatch, status=ProjectStatus.awarded)
    p = seed_tracked(db.session, n=1, status=ProjectStatus.open)
    rec = make_personal_record(db.session, project=p, status="interested")
    db.session.commit()

    await recheck.run_recheck_cycle(db.session, fetcher := FakeFetcher(), FakeSender(),
                                    db.settings, now=NOW)

    assert fetcher.calls  # it was fetched
    assert db.session.get(ProjectScore, p.id).outcome is Outcome.hired
    assert rec.status == "expired_missed"


# 14) _finish_recheck: success vs partial; RECOVERED alert only on a real recovery transition.
async def test_finish_recheck_success_no_recovery_alert(db):
    breaker = recheck.CircuitBreaker(db.session)
    run = ScrapeRun(kind="recheck", started_at=NOW, status=RunStatus.running, error_count=0)
    db.session.add(run)
    db.session.commit()
    sender = FakeSender()

    await recheck._finish_recheck(db.session, breaker, sender, run)

    assert run.status is RunStatus.success
    assert run.finished_at is not None
    assert sender.alerts == []  # was never failing -> no recovery alert


async def test_finish_recheck_partial_when_errors(db):
    breaker = recheck.CircuitBreaker(db.session)
    run = ScrapeRun(kind="recheck", started_at=NOW, status=RunStatus.running, error_count=2)
    db.session.add(run)
    db.session.commit()

    await recheck._finish_recheck(db.session, breaker, FakeSender(), run)

    assert run.status is RunStatus.partial


async def test_finish_recheck_recovery_alerts(db):
    # Pre-seed a failing breaker state so record_success() reports a recovery transition.
    app_state_set(db.session, "cb_consecutive_failures", "3")
    app_state_set(db.session, "cb_resume_at", (NOW + timedelta(minutes=5)).isoformat())
    breaker = recheck.CircuitBreaker(db.session)
    run = ScrapeRun(kind="recheck", started_at=NOW, status=RunStatus.running, error_count=0)
    db.session.add(run)
    db.session.commit()
    sender = FakeSender()

    await recheck._finish_recheck(db.session, breaker, sender, run)

    assert run.status is RunStatus.success
    assert len(sender.alerts) == 1
    assert "RECOVERED" in sender.alerts[0]


# 15) Persisted run carries kind == "recheck".
async def test_run_kind_is_recheck(db, monkeypatch):
    make_parse(monkeypatch)
    seed_tracked(db.session, n=1)
    run = await recheck.run_recheck_cycle(db.session, FakeFetcher(), FakeSender(),
                                          db.settings, now=NOW)

    assert run.kind == "recheck"
    with db.Session() as s2:
        assert s2.get(ScrapeRun, run.id).kind == "recheck"
