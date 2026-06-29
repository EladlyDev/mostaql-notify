"""Feature 4 coverage for worker.main.main(): the one-time scoring backfill + the recheck job.

These exercise the two Feature-4 additions to ``worker/main.py``:

* the startup opportunity-scoring backfill (lines 49->54): runs ``rescore_all`` exactly once,
  commits the scores, and sets the ``app_state`` ``scoring_backfilled`` flag — then is a no-op on
  every later boot (restart) once the flag is ``"true"``;
* the SECOND ``AsyncIOScheduler`` job ``id="recheck"`` (line 106), registered alongside the existing
  ``poll``/``heartbeat`` jobs, whose ``IntervalTrigger`` interval is read from the
  ``recheck_interval_seconds`` setting at registration time and which drives ``run_recheck_cycle``.

Like ``test_worker_main_lifecycle.py`` we never build a real scheduler/bot/network: the ``asyncio``
``Event`` main() awaits is swapped for one that returns immediately, ``AsyncIOScheduler`` is a fake
that records each job's callable + trigger, and ``TelegramSender``/``HttpxFetcher``/``run_*_cycle``
are stubbed. ``rescore_all`` is wrapped in a counting spy so we assert call counts AND that the real
(pure, network-free) scorer actually persisted ``ProjectScore`` rows.
"""
from __future__ import annotations

import asyncio
import types

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import mostaql_notifier.scoring.service as scoring_service
import mostaql_notifier.worker.main as main_mod
from mostaql_notifier.config.settings_store import app_state_get, app_state_set, seed_defaults
from mostaql_notifier.db import models  # noqa: F401  (register tables)
from mostaql_notifier.db.base import Base
from mostaql_notifier.db.models import ProjectScore, Setting
from tests.api.conftest import make_client, make_project

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- fakes


class _FakeEvent:
    def __init__(self):
        self.set_called = False

    def set(self):
        self.set_called = True

    async def wait(self):  # never blocks -> main() proceeds straight to graceful shutdown
        return True


class _FakeScheduler:
    """Records each registered job's callable AND its trigger so we can inspect intervals."""

    last = None

    def __init__(self, *a, **k):
        self.jobs = {}
        self.triggers = {}
        self.listener = None
        self.started = False
        self.shutdown_called = False
        _FakeScheduler.last = self

    def add_job(self, func, trigger=None, id=None, **k):
        self.jobs[id] = func
        self.triggers[id] = trigger

    def add_listener(self, cb, mask):
        self.listener = cb

    def start(self):
        self.started = True

    def shutdown(self, wait=True):
        self.shutdown_called = True


class _FakeSender:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def aclose(self):
        self.closed = True

    async def send_alert(self, text):  # pragma: no cover - not exercised here
        pass

    async def send_heartbeat(self, text):  # pragma: no cover - not exercised here
        pass


class _FakeFetcher:
    def __init__(self, *a, **k):
        self.closed = False

    async def aclose(self):
        self.closed = True


class _FakeRun:
    id = 7
    found_count = 3
    new_count = 1
    updated_count = 0
    error_count = 0
    status = types.SimpleNamespace(value="success")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Patch every external dependency of main() and return a handle with a counting rescore spy."""
    engine = sa.create_engine(f"sqlite:///{tmp_path}/main.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    rescore_calls = {"n": 0, "returned": []}
    real_rescore = scoring_service.rescore_all

    def _spy_rescore(session, *, settings, now_utc):
        rescore_calls["n"] += 1
        scored = real_rescore(session, settings=settings, now_utc=now_utc)
        rescore_calls["returned"].append(scored)
        return scored

    async def _fake_poll(session, fetcher, sender, settings):
        return _FakeRun()

    async def _fake_recheck(session, fetcher, sender, settings):
        return _FakeRun()

    secrets = types.SimpleNamespace(
        telegram_bot_token="tok", telegram_chat_id="chat", database_url="sqlite://"
    )
    fake_fetcher = _FakeFetcher()

    monkeypatch.setattr(main_mod, "get_secrets", lambda: secrets)
    monkeypatch.setattr(main_mod, "upgrade_head", lambda: None)
    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: Session)
    monkeypatch.setattr(main_mod, "TelegramSender", _FakeSender)
    monkeypatch.setattr(main_mod, "HttpxFetcher", lambda: fake_fetcher)
    monkeypatch.setattr(main_mod, "run_poll_cycle", _fake_poll)
    monkeypatch.setattr(main_mod, "run_recheck_cycle", _fake_recheck)
    monkeypatch.setattr(main_mod, "rescore_all", _spy_rescore)
    monkeypatch.setattr(main_mod, "AsyncIOScheduler", _FakeScheduler)
    # Only the Event main() awaits is swapped; the real loop helper is preserved for signal handlers.
    monkeypatch.setattr(
        main_mod,
        "asyncio",
        types.SimpleNamespace(Event=_FakeEvent, get_running_loop=asyncio.get_running_loop),
    )
    _FakeScheduler.last = None
    return types.SimpleNamespace(
        Session=Session, rescore_calls=rescore_calls, fetcher=fake_fetcher
    )


def _set_setting(Session, key: str, value: str) -> None:
    """Seed/override one settings row before main() runs (seed_defaults won't clobber it)."""
    with Session() as s:
        seed_defaults(s)
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value, value_type="int"))
        else:
            row.value = value
        s.commit()


# --------------------------------------------------------------------------- backfill


async def test_backfill_runs_once_scores_projects_and_sets_flag(wired):
    """First boot: rescore_all is called once, qualified projects get a ProjectScore, flag -> true."""
    with wired.Session() as s:
        c = make_client(s)
        p1 = make_project(s, _n=1, client_id=c.id)
        p2 = make_project(s, _n=2, client_id=c.id)
        s.commit()
        p1_id, p2_id = p1.id, p2.id

    await main_mod.main()

    assert wired.rescore_calls["n"] == 1                 # backfill ran exactly once
    assert wired.rescore_calls["returned"] == [2]        # both qualified projects scored
    with wired.Session() as s:
        assert app_state_get(s, "scoring_backfilled") == "true"
        # Scores were COMMITTED (visible in a fresh session post-startup).
        assert s.get(ProjectScore, p1_id) is not None
        assert s.get(ProjectScore, p2_id) is not None
        assert s.get(ProjectScore, p1_id).score is not None


async def test_backfill_skipped_when_flag_already_set(wired):
    """Restart: with scoring_backfilled already "true", rescore_all is NOT called again."""
    with wired.Session() as s:
        c = make_client(s)
        make_project(s, _n=1, client_id=c.id)
        s.commit()
        app_state_set(s, "scoring_backfilled", "true")

    await main_mod.main()

    assert wired.rescore_calls["n"] == 0  # guard branch skipped the backfill on restart
    with wired.Session() as s:
        # The pre-existing qualified project was left unscored (backfill did not run).
        assert s.query(ProjectScore).count() == 0


async def test_backfill_only_runs_on_first_of_two_boots(wired):
    """A second main() boot (flag now persisted) is a no-op: total rescore calls stays at 1."""
    with wired.Session() as s:
        c = make_client(s)
        make_project(s, _n=1, client_id=c.id)
        s.commit()

    await main_mod.main()
    assert wired.rescore_calls["n"] == 1
    with wired.Session() as s:
        assert app_state_get(s, "scoring_backfilled") == "true"

    # Boot again against the same DB — flag is set, so the backfill must not re-run.
    await main_mod.main()
    assert wired.rescore_calls["n"] == 1


async def test_backfill_resilient_with_zero_qualified_projects(wired):
    """Empty DB: backfill still completes, scores nothing, and sets the flag (no error)."""
    await main_mod.main()

    assert wired.rescore_calls["n"] == 1
    assert wired.rescore_calls["returned"] == [0]  # nothing qualified -> zero scored
    with wired.Session() as s:
        assert app_state_get(s, "scoring_backfilled") == "true"
        assert s.query(ProjectScore).count() == 0


# --------------------------------------------------------------------------- scheduler wiring


async def test_scheduler_registers_poll_and_recheck_jobs(wired):
    """Both the existing poll job and the Feature-4 recheck job are registered."""
    await main_mod.main()

    sched = _FakeScheduler.last
    assert sched is not None
    assert {"poll", "recheck"} <= set(sched.jobs)
    assert "heartbeat" in sched.jobs  # existing job is not displaced
    assert sched.started is True


async def test_recheck_interval_matches_default_setting(wired):
    """The recheck job's IntervalTrigger interval equals recheck_interval_seconds (default 1800)."""
    await main_mod.main()

    trigger = _FakeScheduler.last.triggers["recheck"]
    assert trigger.interval.total_seconds() == 1800


async def test_recheck_interval_reflects_changed_setting(wired):
    """Re-tuning recheck_interval_seconds changes the trigger interval (read at registration)."""
    _set_setting(wired.Session, "recheck_interval_seconds", "300")

    await main_mod.main()

    trigger = _FakeScheduler.last.triggers["recheck"]
    assert trigger.interval.total_seconds() == 300


async def test_recheck_job_drives_run_recheck_cycle(wired, monkeypatch):
    """The registered recheck callable invokes run_recheck_cycle when fired."""
    calls = []

    async def _spy_recheck(session, fetcher, sender, settings):
        calls.append(True)
        return _FakeRun()

    monkeypatch.setattr(main_mod, "run_recheck_cycle", _spy_recheck)
    await main_mod.main()
    await _FakeScheduler.last.jobs["recheck"]()
    assert len(calls) == 1


async def test_recheck_job_handles_paused_watcher(wired, monkeypatch):
    """When run_recheck_cycle returns None (watcher paused) the job returns quietly, no error."""
    async def _paused_recheck(session, fetcher, sender, settings):
        return None

    monkeypatch.setattr(main_mod, "run_recheck_cycle", _paused_recheck)
    await main_mod.main()
    # Firing the job must not raise even though there is no run row to log.
    await _FakeScheduler.last.jobs["recheck"]()


# --------------------------------------------------------------------------- lifecycle with recheck


async def test_clean_shutdown_with_recheck_job_present(wired):
    """The graceful-shutdown path still runs cleanly with the recheck job registered."""
    await main_mod.main()

    sched = _FakeScheduler.last
    assert sched.started is True
    assert sched.shutdown_called is True   # scheduler shut down in the finally block
    assert wired.fetcher.closed is True    # fetcher closed on teardown
    assert "recheck" in sched.jobs         # ... and the recheck job was part of that run
